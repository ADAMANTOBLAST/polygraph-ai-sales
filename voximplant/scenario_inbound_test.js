// Вставьте в Voximplant: Scenarios → создать сценарий → JavaScript.
// Привяжите сценарий к приложению и номеру (Applications → Numbers → Attach).
//
// Подставьте публичный HTTPS URL fnr-api, например:
//   https://your-domain.example/voximplant/webhook
// Секрет (если задан VOXIMPLANT_WEBHOOK_SECRET в .env): добавьте ?token=СЕКРЕТ к URL
// или заголовок X-Voximplant-Secret — см. документацию Net.httpRequest в консоли Voximplant.

require(Modules.Net);

var WEBHOOK_URL = "https://YOUR_DOMAIN/voximplant/webhook";
var WEBHOOK_SECRET = ""; // если не пусто — будет ?token=... (удобно без кастомных заголовков)

VoxEngine.addEventListener(AppEvents.CallAlerting, function (event) {
  var call = event.call;
  call.answer();

  var payload = JSON.stringify({
    event: "CallAlerting",
    callerId: call.callerid(),
    destination: call.number(),
    customData: event.customData,
  });

  var url = WEBHOOK_URL;
  if (WEBHOOK_SECRET) {
    url += (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(WEBHOOK_SECRET);
  }

  Net.httpRequest(url, Net.HttpRequestMethod.POST, payload, function (res) {
    Logger.write("voximplant webhook HTTP " + res.code);
  });

  call.say("Test line. Webhook sent to your server.", VoiceList.Amazon.en_US_Joanna);

  call.addEventListener(CallEvents.Disconnected, function () {
    VoxEngine.terminate();
  });
  call.addEventListener(CallEvents.Failed, function () {
    VoxEngine.terminate();
  });
});
