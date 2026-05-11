const DEFAULT_MAX_UPLOAD_SIZE_MB = 512;

function parseMaxUploadSizeMb(value: string | undefined): number {
  if (value === undefined || value.trim() === '') return DEFAULT_MAX_UPLOAD_SIZE_MB;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_MAX_UPLOAD_SIZE_MB;
}

export const MAX_UPLOAD_SIZE_MB = parseMaxUploadSizeMb(import.meta.env.MEDIA_TO_MD_MAX_UPLOAD_MB);
export const MAX_UPLOAD_SIZE_BYTES = Math.floor(MAX_UPLOAD_SIZE_MB * 1024 * 1024);
