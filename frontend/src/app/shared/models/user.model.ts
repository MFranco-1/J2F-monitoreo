// shared/models/user.model.ts
export interface State {
  id: number;
  name: string;
  type: string;
  description?: string;
}

export interface Profile {
  id: number;
  name: string;
  description?: string;
  state_id: number;
  state?: State;
  menu_options?: MenuOption[];
  created_at?: string;
  updated_at?: string;
}

export interface User {
  id: number;
  dni: string;
  full_name: string;
  email: string;
  profile_id?: number | null;
  profile?: Profile | null;
  state_id: number;
  state?: State;
  last_login?: string;
  created_at?: string;
  updated_at?: string;
}

export interface MenuOption {
  id: number;
  name: string;
  url?: string;
  icon?: string | null;
  parent_id?: number | null;
  parent?: MenuOption;
  children?: MenuOption[];
  order?: number;
  state_id: number;
  state?: State;
  profiles?: { id: number; name: string }[];
  created_at?: string;
  updated_at?: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  user: User;
}

export interface CurrentUser {
  id: number;
  email: string;
  full_name: string;
  profile: Profile | null;
}
