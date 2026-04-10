/**
 * Входящий звонок → ElevenLabs Agents (Борис / Flex&Roll PRO).
 *
 * Требуется VoxEngine с модулем ElevenLabs (Voice AI): см.
 * https://docs.voximplant.ai/voice-ai-connectors/elevenlabs/inbound
 *
 * Настройка секретов (Control Panel → приложение → Application storage):
 *   ELEVENLABS_API_KEY   — ключ xi-api-key из https://elevenlabs.io/app/settings/api-keys
 *   ELEVENLABS_AGENT_ID  — например agent_2101kntbp4ekevcspn96s41jfhpz
 * Опционально:
 *   ELEVENLABS_BRANCH_ID — ветка агента, например agtbrch_4901kntbp6rjfy8t3f8ps25fs2jp
 *
 * Промпт и голос задаются в консоли ElevenLabs для этого agent_id, не в сценарии.
 *
 * Опционально: POST на ваш бэкенд (аналитика), как в старом DTMF-сценарии.
 * URL и секрет лучше держать в Application storage: WEBHOOK_URL, WEBHOOK_SECRET.
 */

require(Modules.ElevenLabs);
require(Modules.ApplicationStorage);
require(Modules.Net);

/** Значения по умолчанию, если ключи не заведены в Application storage (только agent/branch — не секреты). */
var DEFAULT_AGENT_ID = "agent_2101kntbp4ekevcspn96s41jfhpz";
var DEFAULT_BRANCH_ID = "agtbrch_4901kntbp6rjfy8t3f8ps25fs2jp";

function postWebhook(url, secret, obj) {
  if (!url || !url.length) return;
  var payload = JSON.stringify(obj);
  var u = url;
  if (secret && secret.length) {
    u += (u.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(secret);
  }
  Net.httpRequest(u, Net.HttpRequestMethod.POST, payload, function (res) {
    Logger.write("webhook HTTP " + res.code);
  });
}

function storageVal(row, fallback) {
  if (row && row.value && String(row.value).length) return String(row.value);
  return fallback || "";
}

VoxEngine.addEventListener(AppEvents.CallAlerting, async function (event) {
  var call = event.call;
  var voiceAIClient;

  call.addEventListener(CallEvents.Disconnected, function () {
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

    var apiKey = storageVal(await ApplicationStorage.get("ELEVENLABS_API_KEY"), "");
    var agentId = storageVal(await ApplicationStorage.get("ELEVENLABS_AGENT_ID"), DEFAULT_AGENT_ID);
    var branchId = storageVal(await ApplicationStorage.get("ELEVENLABS_BRANCH_ID"), DEFAULT_BRANCH_ID);
    var webhookUrl = storageVal(await ApplicationStorage.get("WEBHOOK_URL"), "");
    var webhookSecret = storageVal(await ApplicationStorage.get("WEBHOOK_SECRET"), "");

    if (!apiKey.length) {
      Logger.write("ELEVENLABS_API_KEY missing in Application storage");
      call.hangup();
      return;
    }

    postWebhook(webhookUrl, webhookSecret, {
      event: "CallStart",
      source: "elevenlabs_agents",
      callerId: call.callerid(),
      destination: call.number(),
      agentId: agentId,
      branchId: branchId || undefined,
    });

    // Параметры см. https://voximplant.com/docs/references/voxengine/elevenlabs
    // branch_id: если коннектор ругается на неизвестное поле — уберите блок branchId ниже
    // и задайте ветку по умолчанию в консоли ElevenLabs для этого агента.
    var clientOpts = {
      xiApiKey: apiKey,
      agentId: agentId,
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

    if (branchId && branchId.length) {
      clientOpts.branchId = branchId;
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
