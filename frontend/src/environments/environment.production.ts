declare const J2F_API_URL: string | undefined;

export const environment = {
  production: true,
  apiUrl: typeof J2F_API_URL === 'undefined' ? '/api' : J2F_API_URL,
};
