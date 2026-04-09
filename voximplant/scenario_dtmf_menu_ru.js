// Меню по тонам DTMF: нажмите 1, 2 или 3 — голосом: «Вы перенаправлены на менеджера…».
// Реальное соединение с SIP/менеджером — отдельная настройка в Voximplant; здесь только речь + вебхук.
// Вставьте в Voximplant → Scenarios → JavaScript, привяжите в Routing к входящим.
//
// Требуется только Modules.Net (ASR не нужен).
// Голос: если VoiceList.TBank.ru_RU_Anna не компилируется — выберите русский голос в автодополнении IDE.

require(Modules.Net);

var WEBHOOK_URL = "https://canwant.ru/fnr-api/voximplant/webhook";
var WEBHOOK_SECRET = "";

var voiceRu = VoiceList.TBank.ru_RU_Anna;

function postWebhook(obj) {
  var payload = JSON.stringify(obj);
  var url = WEBHOOK_URL;
  if (WEBHOOK_SECRET) {
    url += (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(WEBHOOK_SECRET);
  }
  Net.httpRequest(url, Net.HttpRequestMethod.POST, payload, function (res) {
    Logger.write("webhook HTTP " + res.code);
  });
}

function sayThenHangup(call, text) {
  call.say(text, voiceRu);
  call.addEventListener(CallEvents.PlaybackFinished, function onEnd() {
    call.removeEventListener(CallEvents.PlaybackFinished, onEnd);
    try {
      call.hangup();
    } catch (e) {
      VoxEngine.terminate();
    }
  });
}

VoxEngine.addEventListener(AppEvents.CallAlerting, function (event) {
  var call = event.call;
  call.answer();

  postWebhook({
    event: "CallStart",
    callerId: call.callerid(),
    destination: call.number(),
  });

  call.handleTones(true);

  var handled = false;

  call.addEventListener(CallEvents.ToneReceived, function onTone(e) {
    if (handled) return;
    var d = e.tone;

    if (d !== "1" && d !== "2" && d !== "3") {
      sayThenHangup(
        call,
        "Неверный выбор. Перезвоните и нажмите один, два или три."
      );
      handled = true;
      call.removeEventListener(CallEvents.ToneReceived, onTone);
      return;
    }

    handled = true;
    call.removeEventListener(CallEvents.ToneReceived, onTone);
    try {
      call.handleTones(false);
    } catch (e2) {}

    postWebhook({
      event: "DtmfMenu",
      callerId: call.callerid(),
      destination: call.number(),
      digit: d,
      choice: d,
      line: "manager_" + d,
    });

    sayThenHangup(
      call,
      "Вы перенаправлены на менеджера. Ожидайте соединения. До свидания."
    );
  });

  call.addEventListener(CallEvents.Disconnected, function () {
    VoxEngine.terminate();
  });
  call.addEventListener(CallEvents.Failed, function () {
    VoxEngine.terminate();
  });

  call.say(
    "Здравствуйте. Чтобы перенаправить звонок на менеджера, нажмите на телефоне: один — первая линия, два — вторая, три — третья.",
    voiceRu
  );
});
