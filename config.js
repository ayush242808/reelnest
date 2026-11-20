// ReelNest site settings. These values are PUBLIC by design: the Supabase anon key only allows
// what the server's Row Level Security rules allow (each signed-in user reaches only their own rows).
// Leave empty to run ReelNest local-only. Never put a service_role key or any secret here.
window.REELNEST_CONFIG = {
  supabaseUrl: "https://gedkntwwjrpfklgvbjtp.supabase.co",
  supabaseAnonKey: "sb_publishable_IAguwzSvnD_1DqFE_LIv9g_aPIBhm_z", // publishable key (public)
  // Google sign-in uses Google ID tokens, so only the public client ID is needed (no client secret).
  googleSignIn: true,
  googleClientId: "437401470628-74k20iojq0gijfukh9fp24hp2d3uql9g.apps.googleusercontent.com",
};
