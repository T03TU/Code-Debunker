export const samples = {
  python: {
    filename: "order.py",
    code: `from dataclasses import dataclass

@dataclass
class Product:
    name: str
    price: float


def subtotal(products: list[Product]) -> float:
    total = sum(product.price for product in products)
    return round(total, 2)


def checkout(products: list[Product], discount: float = 0.1) -> dict:
    amount = subtotal(products)
    savings = round(amount * discount, 2)
    return {"subtotal": amount, "savings": savings, "total": amount - savings}


def main() -> dict:
    basket = [Product("Notebook", 12.0), Product("Pencil", 3.5)]
    return checkout(basket)
`,
  },
  javascript: {
    filename: "order.js",
    code: `export function subtotal(products) {
  return products.reduce((total, product) => total + product.price, 0);
}

export function checkout(products, discount = 0.1) {
  const amount = subtotal(products);
  const savings = Math.round(amount * discount * 100) / 100;
  return { subtotal: amount, savings, total: amount - savings };
}

export function main() {
  const basket = [
    { name: "Notebook", price: 12 },
    { name: "Pencil", price: 3.5 },
  ];
  return checkout(basket);
}
`,
  },
  typescript: {
    filename: "order.ts",
    code: `interface Product {
  name: string;
  price: number;
}

export function subtotal(products: Product[]): number {
  return products.reduce((total, product) => total + product.price, 0);
}

export function checkout(products: Product[], discount: number = 0.1) {
  const amount = subtotal(products);
  const savings = Math.round(amount * discount * 100) / 100;
  return { subtotal: amount, savings, total: amount - savings };
}

export function main() {
  const basket: Product[] = [
    { name: "Notebook", price: 12 },
    { name: "Pencil", price: 3.5 },
  ];
  return checkout(basket);
}
`,
  },
};
