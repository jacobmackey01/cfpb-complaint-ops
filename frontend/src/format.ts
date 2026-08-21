export const formatInteger = (value: number | null | undefined): string =>
  value === null || value === undefined
    ? 'Not available'
    : new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);

export const formatPercent = (
  value: number | null | undefined,
  digits = 1,
): string =>
  value === null || value === undefined
    ? 'Not measured'
    : new Intl.NumberFormat('en-US', {
        style: 'percent',
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(value);

export const formatDecimal = (
  value: number | null | undefined,
  digits = 3,
): string =>
  value === null || value === undefined ? 'Not measured' : value.toFixed(digits);

export const formatDate = (value: string | null | undefined): string => {
  if (!value) return 'Date unavailable';
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date);
};

export const formatDateTime = (value: string | null | undefined): string => {
  if (!value) return 'Time unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  }).format(date);
};

export const formatMoney = (value: number | null | undefined): string =>
  value === null || value === undefined
    ? 'Not measured'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 4,
        maximumFractionDigits: 4,
      }).format(value);

export const sentenceCase = (value: string): string =>
  value.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase());
