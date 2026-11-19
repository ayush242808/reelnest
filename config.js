// ReelNest site settings. These values are PUBLIC by design: the Supabase anon key only allows
// what the server's Row Level Security rules allow (each signed-in user reaches only their own rows).
// Leave empty to run ReelNest local-only. Never put a service_role key or any secret here.
window.REELNEST_CONFIG = {
  supabaseUrl: "",       // e.g. "https://abcdefgh.supabase.co"
  supabaseAnonKey: "",   // Supabase › Project Settings › API › anon public key
  googleSignIn: false,   // true only after enabling Google in Supabase › Authentication › Providers
};
