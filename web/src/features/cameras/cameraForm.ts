// The Add camera form's values and rules. Pure functions: the form derives its errors from its values on
// every render, so nothing is kept in sync by hand.

import {
  CAMERA_DETAIL_MAX,
  CAMERA_NAME_MAX,
  isValidCameraHost,
  STREAM_PASSWORD_MAX,
  STREAM_USERNAME_MAX,
} from '../../api/cameraRules';
import type { CameraCreate } from '../../api/generated/types';

export interface CameraFormValues {
  name: string;
  ip: string;
  username: string;
  /** Only ever held in the form's state until it is sent; cleared after a successful add. */
  streamSecret: string;
  location: string;
  department: string;
  acknowledgeCost: boolean;
}

export type CameraFormField = 'name' | 'ip' | 'username' | 'streamSecret' | 'location' | 'department';

export type CameraFormErrors = Partial<Record<CameraFormField, string>>;

export const EMPTY_CAMERA_FORM: CameraFormValues = {
  name: '',
  ip: '',
  username: '',
  streamSecret: '',
  location: '',
  department: '',
  acknowledgeCost: false,
};

export const IP_HINT = 'Enter an IPv4 address such as 192.168.1.20 or a host name such as cam-1.local, with no port or path.';

/** What is wrong with each field, by the contract's CameraCreate rules. Empty when the fields are valid. */
export function cameraFormErrors(values: CameraFormValues): CameraFormErrors {
  const errors: CameraFormErrors = {};
  const name = values.name.trim();
  if (name.length === 0) errors.name = 'Enter a name for the camera.';
  else if (name.length > CAMERA_NAME_MAX) errors.name = `Use at most ${CAMERA_NAME_MAX} characters.`;

  const host = values.ip.trim();
  if (host.length === 0) errors.ip = "Enter the camera's IP address.";
  else if (!isValidCameraHost(host)) errors.ip = IP_HINT;

  if (values.username.length === 0) errors.username = 'Enter the stream username.';
  else if (values.username.length > STREAM_USERNAME_MAX) errors.username = `Use at most ${STREAM_USERNAME_MAX} characters.`;

  if (values.streamSecret.length === 0) errors.streamSecret = 'Enter the stream password.';
  else if (values.streamSecret.length > STREAM_PASSWORD_MAX) {
    errors.streamSecret = `Use at most ${STREAM_PASSWORD_MAX} characters.`;
  }

  if (values.location.trim().length > CAMERA_DETAIL_MAX) errors.location = `Use at most ${CAMERA_DETAIL_MAX} characters.`;
  if (values.department.trim().length > CAMERA_DETAIL_MAX) {
    errors.department = `Use at most ${CAMERA_DETAIL_MAX} characters.`;
  }
  return errors;
}

function optional(text: string): string | null {
  const trimmed = text.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** The POST /api/cameras body for valid, acknowledged values. */
export function cameraCreateBody(values: CameraFormValues): CameraCreate {
  return {
    name: values.name.trim(),
    ip: values.ip.trim(),
    username: values.username,
    password: values.streamSecret,
    location: optional(values.location),
    department: optional(values.department),
    acknowledgeCost: true,
  };
}
