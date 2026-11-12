// Gizli test verisi ortam değişkenlerinin tipleri (K19, specs/013-sprint-otomasyonu/ANALIZ.md §9).
// Üretilen testler parolayı koda yazmaz: `await loginPage.login("bayi1", process.env.TP_TESTVERI_DEMO_PAROLA);`
// strict + noUncheckedIndexedAccess altında `process.env.X` `string | undefined` olur; bilinen her ad
// burada açıkça `string` bildirilir (dizin imzası kullanılmaz, o yine `| undefined` verir).
// Üretilen testlerin kullandığı YENİ bir gizli test verisi adı (TP_TESTVERI_<AD>) buraya eklenmelidir;
// değer koşuda runner'ın geçirdiği ortamdan gelir (yalnızca ^TP_TESTVERI_[A-Z0-9_]{1,64}$ adları).
// Bu dosya modül değildir (import/export yok): bildirim küresel NodeJS.ProcessEnv'e eklenir.
declare namespace NodeJS {
  interface ProcessEnv {
    readonly TP_TESTVERI_DEMO_PAROLA: string;
  }
}
