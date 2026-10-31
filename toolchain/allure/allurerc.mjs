// test-runner'ın Allure raporu yapılandırması (güvenilir kopya: imajda /opt/allure/allurerc.mjs).
// Commit'teki hiçbir allurerc okunmaz (runner geçici bir çalışma dizininde --config ile çağırır).
// allure2 eklentisi: klasik Allure 2 görünümü, tek dosya (index.html). Analitik
// ALLURE_NO_ANALYTICS=true ile kapalıdır (awesome eklentisi analitiği kapatmaya izin vermez).
export default {
  name: "AI Testing Probe · e2e",
  plugins: {
    allure2: {
      options: { singleFile: true, reportLanguage: "en" },
    },
  },
};
