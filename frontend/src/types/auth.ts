export interface ApiTokenMeta {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

export interface CreateApiTokenResult extends ApiTokenMeta {
  token: string;
}

export interface AccountSummary {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
}

export interface CreateInviteResult {
  token: string;
}
