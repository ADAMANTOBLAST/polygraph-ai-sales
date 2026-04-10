/**
 * ElevenLabs Agents (Екатерина, менеджер) → по client tool transfer_to_specialist перевод на внешний номер.
 * Номер: +375291252472 (Беларусь). Подставьте ключи и верифицированный исходящий Caller ID.
 *
 * Инструкция по настройке: voximplant/SETUP_HANDOFF_RU.txt
 * Промпт для агента: voximplant/elevenlabs_voice_agent_prompt_handoff.txt
 */

require(Modules.ElevenLabs);

/** Журнал звонков в админке fnr-api (POST JSON). Подставьте свой публичный URL и при необходимости секрет из VOXIMPLANT_WEBHOOK_SECRET. */
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

var XI_API_KEY = "";
var ELEVENLABS_AGENT_ID = "agent_2101kntbp4ekevcspn96s41jfhpz";
var ELEVENLABS_BRANCH_ID = "agtbrch_4901kntbp6rjfy8t3f8ps25fs2jp";

/** Куда переводить лида (E.164) */
var SPECIALIST_PSTN = "+375291252472";

/**
 * Исходящий Caller ID для ноги callPSTN — должен быть подтверждён в Voximplant (часто ваш входящий DID).
 * Пример: +74999384362 — замените на свой.
 */
var OUTBOUND_CALLER_ID = "+74999384362";

/** Имя client tool в ElevenLabs должно совпадать посимвольно */
var TOOL_HANDOFF = "transfer_to_specialist";

/**
 * ElevenLabs шлёт разные формы payload; раньше при отсутствии tool_call_id сценарий выходил и перевод не шёл.
 */
function extractClientToolPayload(event) {
  var raw = event && event.data !== undefined ? event.data : event;
  var payload = raw && raw.payload !== undefined ? raw.payload : raw || {};
  try {
    Logger.write("ClientToolCall payload: " + JSON.stringify(payload));
  } catch (logErr) {
    Logger.write("ClientToolCall (payload not stringifiable)");
  }
  var toolName = payload.tool_name || payload.toolName || payload.name;
  var toolCallId = payload.tool_call_id || payload.toolCallId || payload.id;
  var tc = payload.tool_calls;
  if (tc && tc.length) {
    var first = tc[0];
    toolName = toolName || first.name || (first.function && first.function.name);
    toolCallId = toolCallId || first.id || first.tool_call_id;
  }
  if (toolName && String(toolName).toLowerCase() === TOOL_HANDOFF.toLowerCase()) {
    toolName = TOOL_HANDOFF;
  }
  if (!toolCallId && toolName === TOOL_HANDOFF) {
    toolCallId = "fallback_" + Date.now();
    Logger.write("ClientToolCall: tool_call_id отсутствует, используем fallback для перевода");
  }
  return { toolName: toolName, toolCallId: toolCallId, payload: payload };
}

function doHandoffPSTN(call, voiceAIClient) {
  try {
    voiceAIClient.close();
  } catch (eClose) {}

  var specialistLeg = VoxEngine.callPSTN(SPECIALIST_PSTN, OUTBOUND_CALLER_ID);

  specialistLeg.addEventListener(CallEvents.Connected, function () {
    VoxEngine.sendMediaBetween(call, specialistLeg);
  });

  specialistLeg.addEventListener(CallEvents.Failed, function (ev) {
    Logger.write("SPECIALIST_PSTN Failed");
    Logger.write(JSON.stringify(ev));
    try {
      call.hangup();
    } catch (eFail) {}
  });

  specialistLeg.addEventListener(CallEvents.Disconnected, function () {
    try {
      call.hangup();
    } catch (eDisc) {}
  });
}

VoxEngine.addEventListener(AppEvents.CallAlerting, async function (event) {
  var call = event.call;
  var voiceAIClient;
  var transferred = false;
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
      source: "voximplant_elevenlabs_handoff",
      session_id: String(call.id()),
      caller_id: String(call.callerid()),
      destination: dest,
      duration_sec: dur,
      transferred_to_specialist: transferred,
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
      Logger.write("XI_API_KEY пустой");
      call.hangup();
      return;
    }

    var clientOpts = {
      xiApiKey: XI_API_KEY,
      agentId: ELEVENLABS_AGENT_ID,
      onWebSocketClose: function (wsEvent) {
        Logger.write("===ElevenLabs.WebSocket.Close===");
        if (transferred) return;
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
      voiceAIClient.clearMediaBuffer();
    });

    voiceAIClient.addEventListener(ElevenLabs.AgentsEvents.ClientToolCall, function (event) {
      var extracted = extractClientToolPayload(event);
      var toolName = extracted.toolName;
      var toolCallId = extracted.toolCallId;

      if (!toolName) {
        Logger.write("ClientToolCall: нет tool name в payload");
        return;
      }

      if (toolName !== TOOL_HANDOFF) {
        if (toolCallId) {
          voiceAIClient.clientToolResult({
            tool_call_id: toolCallId,
            tool_name: toolName,
            result: { error: "unknown_tool", got: toolName },
          });
        }
        return;
      }

      if (!toolCallId) {
        Logger.write("ClientToolCall: критично — нет tool_call_id даже после fallback");
        return;
      }

      voiceAIClient.clientToolResult({
        tool_call_id: toolCallId,
        tool_name: toolName,
        result: { ok: true, message: "transfer_started" },
      });

      transferred = true;
      doHandoffPSTN(call, voiceAIClient);
    });

    if (ElevenLabs.AgentsEvents.AgentToolResponse) {
      voiceAIClient.addEventListener(ElevenLabs.AgentsEvents.AgentToolResponse, function (ev) {
        Logger.write("AgentToolResponse (server tools / отладка):");
        try {
          Logger.write(JSON.stringify(ev && ev.data !== undefined ? ev.data : ev));
        } catch (eAtr) {}
      });
    }

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
      Logger.write("WebSocketError");
      if (ev && ev.data) Logger.write(JSON.stringify(ev.data));
    });
  } catch (error) {
    Logger.write("===UNHANDLED_ERROR===");
    Logger.write(error);
    try {
      voiceAIClient && voiceAIClient.close();
    } catch (e7) {}
    call.hangup();
  }
});
