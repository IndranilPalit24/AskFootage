// Camera rules from contract/openapi.yaml (CameraCreate and Camera.rtspUrlMasked). The demo client and the
// Add camera form both use these, so the form never accepts what the API would refuse, and the masked URL
// the form previews is built exactly like the one the API returns.

import type { CameraStatus } from './generated/types';

export const CAMERA_NAME_MAX = 80;
export const CAMERA_HOST_MAX = 253;
export const STREAM_USERNAME_MAX = 64;
export const STREAM_PASSWORD_MAX = 128;
/** Location and department. */
export const CAMERA_DETAIL_MAX = 80;

/** Stands in for the stream password everywhere; the real one is never shown or returned. */
export const MASKED_PASSWORD = '****';

export const CAMERA_STATUSES: readonly CameraStatus[] = ['online', 'standby', 'offline'];

export const CAMERA_STATUS_LABEL: Record<CameraStatus, string> = {
  online: 'Online',
  standby: 'Standby',
  offline: 'Offline',
};

export function isCameraStatus(value: unknown): value is CameraStatus {
  return value === 'online' || value === 'standby' || value === 'offline';
}

const HEX = '0123456789ABCDEF';

/** True for the bytes of A-Z a-z 0-9 - . _ ~ (RFC 3986 unreserved). */
function isUnreserved(byte: number): boolean {
  return (
    (byte >= 0x30 && byte <= 0x39) ||
    (byte >= 0x41 && byte <= 0x5a) ||
    (byte >= 0x61 && byte <= 0x7a) ||
    byte === 0x2d ||
    byte === 0x2e ||
    byte === 0x5f ||
    byte === 0x7e
  );
}

const utf8 = new TextEncoder();

/**
 * The stream username as it appears in rtspUrlMasked: every character except A-Z a-z 0-9 - . _ ~ becomes
 * %XX of its UTF-8 bytes, upper-case hex. That is encodeURIComponent plus ! ' ( ) * encoded as well.
 * "a@b:c" -> "a%40b%3Ac".
 */
export function encodeStreamUsername(username: string): string {
  let out = '';
  for (const byte of utf8.encode(username)) {
    out += isUnreserved(byte) ? String.fromCharCode(byte) : `%${HEX[byte >> 4]}${HEX[byte & 15]}`;
  }
  return out;
}

function rtspUrl(userPart: string, host: string): string {
  return `rtsp://${userPart}:${MASKED_PASSWORD}@${host}:554/cam/realmonitor?channel=1&subtype=1`;
}

/** rtsp://<encoded username>:****@<host>:554/cam/realmonitor?channel=1&subtype=1. It never takes a password. */
export function maskedRtspUrl(username: string, host: string): string {
  return rtspUrl(encodeStreamUsername(username), host);
}

/** The same URL while a form is being filled in: a blank username or host shows as <username> or <ip>. */
export function maskedRtspUrlPreview(username: string, host: string): string {
  return rtspUrl(username ? encodeStreamUsername(username) : '<username>', host || '<ip>');
}

/** CameraCreate.ip's pattern: labels of letters, digits and inner hyphens, separated by dots. */
const HOST_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$/;
const DIGITS_AND_DOTS = /^[0-9.]+$/;
/** 0-255 with no leading zero (as Python's ipaddress module reads an IPv4 address). */
const IPV4_PART = /^(?:0|[1-9][0-9]{0,2})$/;

/**
 * True for an IPv4 address (four numbers 0-255 separated by dots) or a host name, as CameraCreate.ip allows:
 * no spaces, scheme, port, user or path, at most 253 characters, and a value made only of digits and dots
 * must be a valid IPv4 address.
 */
export function isValidCameraHost(value: string): boolean {
  if (value.length === 0 || value.length > CAMERA_HOST_MAX || !HOST_PATTERN.test(value)) return false;
  if (!DIGITS_AND_DOTS.test(value)) return true;
  const parts = value.split('.');
  return parts.length === 4 && parts.every((part) => IPV4_PART.test(part) && Number(part) <= 255);
}

const CAMERA_ID = /^CAM-(\d+)$/;

/** CAM-007 -> 7; anything else -> Infinity, so it sorts last. */
export function cameraIdNumber(id: string): number {
  const match = CAMERA_ID.exec(id);
  return match ? Number(match[1]) : Number.POSITIVE_INFINITY;
}

/** "CAM-001" for 1, "CAM-1000" for 1000. */
export function cameraIdFor(number: number): string {
  return `CAM-${String(number).padStart(3, '0')}`;
}

/** Id order, which is creation order (CAM-999 before CAM-1000). */
export function byCameraId(a: { id: string }, b: { id: string }): number {
  return cameraIdNumber(a.id) - cameraIdNumber(b.id) || a.id.localeCompare(b.id);
}
