import { AdminSession } from '../types/api';

const tokenKey = 'whisperx_admin_token';
const usernameKey = 'whisperx_admin_username';

export interface StoredAdminSession {
  token: string;
  username: string | null;
}

export class AdminSessionStore {
  constructor(private readonly storage: Storage = window.localStorage) {}

  read(): StoredAdminSession | null {
    const token = this.storage.getItem(tokenKey);
    if (!token) return null;
    return {
      token,
      username: this.storage.getItem(usernameKey),
    };
  }

  save(session: AdminSession): void {
    this.storage.setItem(tokenKey, session.accessToken);
    this.storage.setItem(usernameKey, session.username);
  }

  clear(): void {
    this.storage.removeItem(tokenKey);
    this.storage.removeItem(usernameKey);
  }
}
