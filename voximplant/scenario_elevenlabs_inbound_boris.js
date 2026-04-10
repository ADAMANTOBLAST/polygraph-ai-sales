/**
 * Входящий звонок → ElevenLabs Agents (Борис / Flex&Roll PRO).
 * Секреты — константы ниже. Без Modules.Net: на части аккаунтов require(Modules.Net) даёт
 * «empty module argument» и рвёт сценарий; официальный пример ElevenLabs тоже без Net.
 *
 * https://docs.voximplant.ai/voice-ai-connectors/elevenlabs/inbound
 */

require(Modules.ElevenLabs);

/** Журнал звонков в админке fnr-api */
var FNR_VOICE_WEBHOOK_URL = "https://canwant.ru/fnr-api/voximplant/webhook";
var FNR_VOICE_WEBHOOK_SECRET = "";

var _fnrVoiceNetOk = false;
try {
  require(Modules.Net);
  _fnrVoiceNetOk = true;
} catch (_eNet) {
  Logger.write("voice log: Modules.Net недоступен — журнал в админке отключён");
}

function fnrPostVoiceCall(payload) {
  if (!_fnrVoiceNetOk) return;
  var body = JSON.stringify(payload);
  var url = FNR_VOICE_WEBHOOK_URL;
  if (FNR_VOICE_WEBHOOK_SECRET && FNR_VOICE_WEBHOOK_SECRET.length) {
    url += (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(FNR_VOICE_WEBHOOK_SECRET);
  }
  Net.httpRequest(url, Net.HttpRequestMethod.POST, body, function (res) {
    Logger.write("fnr voice log HTTP " + (res && res.code != null ? res.code : "?"));
  });
}

// ============ Подставьте свои значения ============
/** xi-api-key из https://elevenlabs.io/app/settings/api-keys */
var XI_API_KEY = "";

/** ID агента в консоли ElevenLabs */
var ELEVENLABS_AGENT_ID = "agent_2101kntbp4ekevcspn96s41jfhpz";

/** Ветка агента (если не нужна — "" и убери блок branchId ниже) */
var ELEVENLABS_BRANCH_ID = "agtbrch_4901kntbp6rjfy8t3f8ps25fs2jp";
// ================================================

VoxEngine.addEventListener(AppEvents.CallAlerting, async function (event) {
  var call = event.call;
  var voiceAIClient;
  var voiceStartedAt = 0;

  call.addEventListener(CallEvents.Connected, function () {
    voiceStartedAt = Date.now();
  });

  call.addEventListener(CallEvents.Disconnected, function () {
    var dur = voiceStartedAt ? Math.max(0, Math.floor((Date.now() - voiceStartedAt) / 1000)) : 0;
    var dest = "";
    try {
      dest = call.number() ? String(call.number()) : "";
    } catch (_n) {}
    fnrPostVoiceCall({
      event: "call_ended",
      source: "voximplant_elevenlabs_inbound",
      session_id: String(call.id()),
      caller_id: String(call.callerid()),
      destination: dest,
      duration_sec: dur,
    });
    try {
      voiceAIClient && voiceAIClient.close();
    } catch (e1) {}
    VoxEngine.terminate();
  });
  call.addEventListener(CallEvents.Failed, function () {
    try {
      voiceAIClient && voiceAIClient.close();
    } catch (e2) {}
    VoxEngine.terminate();
  });

  try {
    call.answer();

    if (!XI_API_KEY || !XI_API_KEY.length) {
      Logger.write("XI_API_KEY пустой — вставьте ключ ElevenLabs в начале сценария");
      call.hangup();
      return;
    }

    var clientOpts = {
      xiApiKey: XI_API_KEY,
      agentId: ELEVENLABS_AGENT_ID,
      onWebSocketClose: function (wsEvent) {
        Logger.write("===ElevenLabs.WebSocket.Close===");
        if (wsEvent) Logger.write(JSON.stringify(wsEvent));
        try {
          call.hangup();
        } catch (e3) {
          VoxEngine.terminate();
        }
      },
    };

    if (ELEVENLABS_BRANCH_ID && ELEVENLABS_BRANCH_ID.length) {
      clientOpts.branchId = ELEVENLABS_BRANCH_ID;
    }

    voiceAIClient = await ElevenLabs.createAgentsClient(clientOpts);

    VoxEngine.sendMediaBetween(call, voiceAIClient);

    voiceAIClient.addEventListener(ElevenLabs.AgentsEvents.Interruption, function () {
      Logger.write("===BARGE-IN===");
      voiceAIClient.clearMediaBuffer();
    });

    voiceAIClient.addEventListener(ElevenLabs.AgentsEvents.UserTranscript, function (ev) {
      var payload = ev && ev.data ? ev.data.payload || ev.data : {};
      var text = payload.text || payload.transcript || payload.user_transcript;
      if (text) Logger.write("USER: " + text);
    });

    voiceAIClient.addEventListener(ElevenLabs.AgentsEvents.AgentResponse, function (ev) {
      var payload = ev && ev.data ? ev.data.payload || ev.data : {};
      var text = payload.text || payload.response || payload.agent_response;
      if (text) Logger.write("AGENT: " + text);
    });

    voiceAIClient.addEventListener(ElevenLabs.AgentsEvents.WebSocketError, function (ev) {
      Logger.write("===ElevenLabs WebSocketError===");
      if (ev && ev.data) Logger.write(JSON.stringify(ev.data));
    });
  } catch (error) {
    Logger.write("===UNHANDLED_ERROR===");
    Logger.write(error);
    try {
      voiceAIClient && voiceAIClient.close();
    } catch (e4) {}
    call.hangup();
  }
});
