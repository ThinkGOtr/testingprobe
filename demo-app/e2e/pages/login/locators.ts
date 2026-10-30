// Giriş sayfası locator'ları — saf veri.
export const login = {
  username: { testId: "login-username", role: "textbox", name: "Kullanıcı adı", intent: "Giriş formunda kullanıcı adı alanı" },
  password: { testId: "login-password", role: "textbox", name: "Parola", intent: "Giriş formunda parola alanı" },
  submit: { testId: "login-submit", role: "button", name: "Giriş yap", intent: "Giriş formunu gönderen buton" },
  error: { testId: "login-error", role: "alert", name: "", intent: "Hatalı girişte gösterilen hata mesajı" },
} as const;
