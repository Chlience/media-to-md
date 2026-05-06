import { DEFAULT_API_BASE_URL } from '../types/api';

const API_BASE_URL_STORAGE_KEY = 'media_to_md_api_base_url';

function canUseLocalStorage(): boolean {
  try {
    return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
  } catch {
    return false;
  }
}

export function normalizeApiBaseUrl(value: string | null | undefined): string {
  const trimmed = (value ?? '').trim();
  if (!trimmed) return DEFAULT_API_BASE_URL;
  return trimmed.replace(/\/+$/, '');
}

export function readApiBaseUrl(): string {
  if (!canUseLocalStorage()) return DEFAULT_API_BASE_URL;
  return normalizeApiBaseUrl(window.localStorage.getItem(API_BASE_URL_STORAGE_KEY));
}

export function saveApiBaseUrl(value: string): string {
  const normalized = normalizeApiBaseUrl(value);
  if (canUseLocalStorage()) {
    window.localStorage.setItem(API_BASE_URL_STORAGE_KEY, normalized);
  }
  return normalized;
}
