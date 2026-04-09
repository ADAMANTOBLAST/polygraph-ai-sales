// Голосовое меню: распознавание речи (ASR) + простые «команды» по ключевым словам.
// Вставьте в Voximplant → Scenarios → JavaScript.
//
// ВАЖНО:
// - ASR в Voximplant тарифицируется отдельно. Проверьте баланс и цены в личном кабинете.
// - Если IDE подсвечивает голос — замените второй аргумент call.say на подсказку из автодополнения
//   (русские голоса: TBank, Yandex, Google и т.д.).
// - Проще и дешевле: сценарий с DTMF (нажмите 1/2/3) — см. комментарий внизу.
//
// require: в панели сценариев должны быть доступны модули Net и ASR.

require(Modules.Net);
require(Modules.ASR);

var WEBHOOK_URL = "https://canwant.ru/fnr-api/voximplant/webhook";
var WEBHOOK_SECRET = "";

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

/** Подстройте слова под бизнес (латиница не нужна — сравниваем после toLowerCase). */
function detectCommand(text) {
  var t = (text || "").toLowerCase();
  if (t.indexOf("заказ") >= 0) return "order";
  if (t.indexOf("менеджер") >= 0 || t.indexOf("оператор") >= 0) return "manager";
  if (t.indexOf("справк") >= 0) return "help";
  return "unknown";
}

VoxEngine.addEventListener(AppEvents.CallAlerting, function (event) {
  var call = event.call;
  call.answer();

  postWebhook({
    event: "CallStart",
    callerId: call.callerid(),
    destination: call.number(),
  });

  var asr = null;

  function terminateSafe() {
    try {
      if (asr) asr.stop();
    } catch (e1) {}
    VoxEngine.terminate();
  }

  call.addEventListener(CallEvents.Disconnected, terminateSafe);
  call.addEventListener(CallEvents.Failed, terminateSafe);

  // Голос: при ошибке компиляции замените на VoiceList.* из документации (русский TBank/Yandex).
  var voiceRu = VoiceList.TBank.ru_RU_Anna;

  call.say(
    "Здравствуйте. После этого сообщения скажите коротко: заказ, менеджер или справка.",
    voiceRu
  );

  call.addEventListener(CallEvents.PlaybackFinished, function onPromptDone() {
    call.removeEventListener(CallEvents.PlaybackFinished, onPromptDone);

    asr = VoxEngine.createASR({ lang: ASRLanguage.RUSSIAN_RU });
    asr.addEventListener(ASREvents.Result, function (ev) {
      try {
        asr.stop();
      } catch (e2) {}

      var text = ev.text || "";
      var cmd = detectCommand(text);
      postWebhook({
        event: "VoiceCommand",
        callerId: call.callerid(),
        destination: call.number(),
        rawText: text,
        confidence: ev.confidence,
        command: cmd,
      });

      var reply = "Не смогли распознать. Перезвоните позже.";
      if (cmd === "order") reply = "Оформление заказа. С вами свяжутся.";
      else if (cmd === "manager") reply = "Переводим на менеджера. Ожидайте.";
      else if (cmd === "help") reply = "Справка. Подробности на сайте компании.";

      call.say(reply, voiceRu);
      call.addEventListener(CallEvents.PlaybackFinished, function hangupAfterReply() {
        call.removeEventListener(CallEvents.PlaybackFinished, hangupAfterReply);
        call.hangup();
      });
    });

    call.sendMediaTo(asr);
  });
});

/*
 * --- Альтернатива без голоса: DTMF (дёшево, стабильно) ---
 * После call.answer():
 *   call.handleTones(true);
 *   call.addEventListener(CallEvents.ToneReceived, function (e) {
 *     var d = e.tone; // '1','2','3'
 *     postWebhook({ event: "Dtmf", digit: d, callerId: call.callerid() });
 *   });
 * И проигрывать call.say("Нажмите один для заказа, два для менеджера...");
 */
