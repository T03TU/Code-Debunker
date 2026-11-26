"""CodeDebunker API: deterministic analysis, grounded explanations, isolated tests."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Literal
import uuid

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.debunk.llm import generate_debunk_async, generate_tests_async, test_connection
from app.llm_settings import LLMSettings, SettingsUpdate, get_settings, resolve_update, save_settings
from app.debunk.uml_builder import build_class_diagram, build_dataflow_diagram
from app.models.ir import IRSlice, ProgramIR
from app.models.llm import DebunkResponse, GeneratedTestSuite
from app.models.uml import UMLDiagram
from app.parser.graph_slicer import GraphSlicer
from app.parser.ir_builder import build_program_ir
from app.sandbox.qa_gate import QAGater
from app.sandbox.runner import DockerSandboxRunner, SandboxExecutionResult

logger = logging.getLogger('codedebunk.api')
app = FastAPI(title='CodeDebunker API', version='1.0.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(','),
    allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Content-Type'],
)
_sessions: dict[str, dict[str, Any]] = {}
SESSION_TTL = 3600
MAX_SESSIONS = 100


class AnalyzeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200_000)
    filename: str | None = Field(None, max_length=255)
    language: Literal['python', 'javascript', 'typescript'] | None = None


class AnalyzeResponse(BaseModel):
    analysis_id: str
    ir: ProgramIR
    class_diagram: UMLDiagram
    dataflow_diagram: UMLDiagram | None = None
    entry_point_symbol_id: str | None = None


class SimulateRequest(BaseModel):
    target_symbol_id: str | None = None


class SimulateResponse(BaseModel):
    analysis_id: str
    target_symbol_id: str
    test_code: str
    execution: SandboxExecutionResult


class SliceResponse(BaseModel):
    slice: IRSlice
    dataflow_diagram: UMLDiagram


def _prune_sessions() -> None:
    now = time.monotonic()
    for key in list(_sessions):
        if now - _sessions[key]['created_at'] > SESSION_TTL:
            del _sessions[key]


def _session(analysis_id: str) -> dict[str, Any]:
    _prune_sessions()
    if analysis_id not in _sessions:
        raise HTTPException(404, 'Analysis not found or expired. Analyze your source again.')
    return _sessions[analysis_id]


def _slice(ir: ProgramIR, symbol_id: str | None) -> IRSlice:
    try:
        return GraphSlicer(ir).extract_1hop_slice(symbol_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def _require_llm(settings: LLMSettings) -> None:
    if not settings.configured:
        raise HTTPException(503, 'Open LLM settings to choose a provider, model, and credentials. Structural analysis works without an LLM.')


async def _debunk(session: dict[str, Any], ir_slice: IRSlice, settings: LLMSettings) -> DebunkResponse:
    target = (settings.fingerprint, ir_slice.target_symbol_id)
    if target in session['debunks']:
        return session['debunks'][target]
    feedback = None
    for _ in range(2):
        result = await generate_debunk_async(ir_slice, feedback=feedback, settings=settings)
        qa = QAGater.audit_all(
            ir=session['ir'], ir_slice=ir_slice, language_id=result.language_identification,
            feynman_explanation=result.feynman_explanation, annotated_code=result.annotated_code,
            walkthrough=result.simulated_walkthrough, prerequisites=[c.name for c in result.prerequisite_concepts],
        )
        if qa.passed:
            session['debunks'][target] = result
            return result
        feedback = '\n'.join(qa.errors)
    raise ValueError('Explanation failed validation after one retry: ' + (feedback or 'unknown error'))


async def _tests(session: dict[str, Any], ir_slice: IRSlice, settings: LLMSettings) -> GeneratedTestSuite:
    target = (settings.fingerprint, ir_slice.target_symbol_id)
    if target in session['tests']:
        return session['tests'][target]
    feedback = None
    for _ in range(2):
        result = await generate_tests_async(ir_slice, feedback=feedback, settings=settings)
        errors = QAGater.validate_tests(ir_slice, result)
        if not errors:
            session['tests'][target] = result
            return result
        feedback = '\n'.join(errors)
    raise ValueError('Test generation failed validation after one retry: ' + (feedback or 'unknown error'))


@app.post('/api/analyze', response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not req.code.strip():
        raise HTTPException(422, 'Source code must not be empty.')
    if len(req.code.encode('utf-8')) > 200_000:
        raise HTTPException(413, 'Source must be smaller than 200 KB.')
    analysis_id = f'analysis_{uuid.uuid4().hex}'
    try:
        ir = await asyncio.to_thread(build_program_ir, source_code=req.code,
                                     file_path=req.filename or 'snippet', language=req.language,
                                     analysis_id=analysis_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    diagram = build_class_diagram(ir)
    primary = ir.metadata.entry_points[0] if ir.metadata.entry_points else None
    flow = build_dataflow_diagram(_slice(ir, primary)) if ir.symbols.callables else None
    _prune_sessions()
    while len(_sessions) >= MAX_SESSIONS:
        del _sessions[next(iter(_sessions))]
    _sessions[analysis_id] = {'ir': ir, 'code': req.code, 'created_at': time.monotonic(), 'debunks': {}, 'tests': {}}
    return AnalyzeResponse(analysis_id=analysis_id, ir=ir, class_diagram=diagram,
                           dataflow_diagram=flow, entry_point_symbol_id=primary)


@app.get('/api/slice/{analysis_id}', response_model=SliceResponse)
async def get_slice(analysis_id: str, symbol_id: str | None = Query(None)) -> SliceResponse:
    ir_slice = _slice(_session(analysis_id)['ir'], symbol_id)
    return SliceResponse(slice=ir_slice, dataflow_diagram=build_dataflow_diagram(ir_slice))


@app.get('/api/stream/{analysis_id}')
async def stream_debunk(analysis_id: str, symbol_id: str | None = Query(None)):
    session = _session(analysis_id)
    ir_slice = _slice(session['ir'], symbol_id)
    settings = get_settings()
    _require_llm(settings)

    def event(name, data):
        return {'event': name, 'data': json.dumps(data)}

    async def events():
        tasks = []
        try:
            yield event('slice_ready', {'target_symbol_id': ir_slice.target_symbol_id, 'target_name': ir_slice.target_callable.name})
            tasks = [asyncio.create_task(_debunk(session, ir_slice, settings)), asyncio.create_task(_tests(session, ir_slice, settings))]
            # Validate each artifact before publishing it; tests may finish after explanations.
            debunk = await tasks[0]
            for name in ('language_identification', 'feynman_explanation', 'annotated_code',
                         'simulated_walkthrough', 'prerequisite_concepts'):
                content = getattr(debunk, name)
                if name == 'prerequisite_concepts':
                    content = json.dumps([concept.model_dump() for concept in content])
                yield event('section', {'name': name, 'content': content})
            tests = await tasks[1]
            yield event('tests', tests.model_dump())
            yield event('qa_result', {'passed': True, 'errors': []})
            yield event('done', {})
        except Exception:
            # Provider exceptions may contain authorization headers or credential-bearing bodies.
            logger.warning('Generation failed for %s', analysis_id)
            yield event('error', {'message': 'Generation failed or failed validation. Open LLM settings to test the provider, model, credentials, and output mode.'})
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    return EventSourceResponse(events())


@app.post('/api/simulate/{analysis_id}', response_model=SimulateResponse)
async def simulate(analysis_id: str, req: SimulateRequest) -> SimulateResponse:
    session = _session(analysis_id)
    ir_slice = _slice(session['ir'], req.target_symbol_id)
    settings = get_settings()
    runner = DockerSandboxRunner()
    available, reason = await asyncio.to_thread(runner.availability)
    if not available:
        raise HTTPException(503, reason)
    if (settings.fingerprint, ir_slice.target_symbol_id) not in session['tests']:
        _require_llm(settings)
    try:
        tests = await _tests(session, ir_slice, settings)
    except Exception as error:
        logger.warning('Test generation failed')
        raise HTTPException(502, 'Test generation failed or failed validation. Open LLM settings and test the connection.') from error
    execution = await asyncio.to_thread(runner.run_tests, source_code=session['code'],
                                       test_code=tests.test_code, language=ir_slice.primary_language)
    return SimulateResponse(analysis_id=analysis_id, target_symbol_id=ir_slice.target_symbol_id,
                            test_code=tests.test_code, execution=execution)


@app.get('/api/capabilities')
async def capabilities():
    available, reason = await asyncio.to_thread(DockerSandboxRunner().availability)
    return {'languages': ['python', 'javascript', 'typescript'],
            'llm_configured': get_settings().configured, 'sandbox_available': available,
            'sandbox_message': reason, 'max_source_bytes': 200_000}


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith('/api/llm-settings'):
        # Pydantic normally echoes invalid inputs, which can include credentials.
        return JSONResponse(status_code=422, content={'detail': [
            {'loc': list(item['loc']), 'msg': item['msg'], 'type': item['type']}
            for item in error.errors()
        ]})
    return await request_validation_exception_handler(request, error)


@app.get('/api/llm-settings')
async def llm_settings():
    return get_settings().public_dict()


@app.post('/api/llm-settings')
async def update_llm_settings(update: SettingsUpdate):
    settings = resolve_update(update)
    if not settings.configured:
        raise HTTPException(422, 'Enter an API key for the selected provider.')
    try:
        save_settings(settings)
    except OSError:
        raise HTTPException(500, 'Could not save LLM settings. Check local configuration directory permissions.') from None
    return settings.public_dict()


@app.post('/api/llm-settings/test')
async def check_llm_connection(update: SettingsUpdate):
    settings = resolve_update(update)
    if not settings.configured:
        raise HTTPException(422, 'Enter an API key for the selected provider.')
    try:
        await asyncio.wait_for(test_connection(settings), timeout=30)
    except Exception:
        raise HTTPException(502, 'Connection or structured-output check failed. Check the endpoint, model, credentials, and output mode. Ensure a local model server is running.') from None
    return {'ok': True, 'message': 'Connected. The model returned valid structured output.'}


@app.get('/health')
async def health():
    return {'status': 'ok', 'version': '1.0.0'}


# A production build can be served by FastAPI on one origin, without Vite.
frontend_dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if frontend_dist.is_dir():
    app.mount('/', StaticFiles(directory=frontend_dist, html=True), name='frontend')
