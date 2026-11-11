// Small formatting helpers.
export function formatPrice(amount: number, currency: string = "SGD"): string {
  return `${currency} ${amount.toFixed(2)}`;
}

export const slugify = (text: string) => text.toLowerCase().replace(/ /g, "-");

export const shout = (text: string) => text.toUpperCase();
