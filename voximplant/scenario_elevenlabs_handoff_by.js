/**
 * ElevenLabs Agents (Екатерина, менеджер) → по client tool transfer_to_specialist перевод на внешний номер.
 * Номер: +375291252472 (Беларусь). Подставьте ключи и верифицированный исходящий Caller ID.
 *
 * Инструкция по настройке: voximplant/SETUP_HANDOFF_RU.txt
 * Промпт для агента: voximplant/elevenlabs_voice_agent_prompt_handoff.txt
 */

require(Modules.ElevenLabs);

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

VoxEngine.addEventListener(AppEvents.CallAlerting, async function (event) {
  var call = event.call;
  var voiceAIClient;
  var transferred = false;

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
      var payload = event && event.data ? event.data.payload || event.data : {};
      var toolName = payload.tool_name || payload.toolName || payload.name;
      var toolCallId = payload.tool_call_id || payload.toolCallId || payload.id;

      if (!toolName || !toolCallId) {
        Logger.write("ClientToolCall: нет tool name или id");
        return;
      }

      if (toolName !== TOOL_HANDOFF) {
        voiceAIClient.clientToolResult({
          tool_call_id: toolCallId,
          tool_name: toolName,
          result: { error: "unknown_tool", got: toolName },
        });
        return;
      }

      voiceAIClient.clientToolResult({
        tool_call_id: toolCallId,
        tool_name: toolName,
        result: { ok: true, message: "transfer_started" },
      });

      transferred = true;

      try {
        voiceAIClient.close();
      } catch (e4) {}

      var specialistLeg = VoxEngine.callPSTN(SPECIALIST_PSTN, OUTBOUND_CALLER_ID);

      specialistLeg.addEventListener(CallEvents.Connected, function () {
        VoxEngine.sendMediaBetween(call, specialistLeg);
      });

      specialistLeg.addEventListener(CallEvents.Failed, function (ev) {
        Logger.write("SPECIALIST_PSTN Failed");
        Logger.write(JSON.stringify(ev));
        try {
          call.hangup();
        } catch (e5) {}
      });

      specialistLeg.addEventListener(CallEvents.Disconnected, function () {
        try {
          call.hangup();
        } catch (e6) {}
      });
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
