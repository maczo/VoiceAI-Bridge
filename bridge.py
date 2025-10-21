import os
import asyncio
import threading
import time
from pjsua2 import *  # PJSIP bindings for SIP/RTP
from deepgram import DeepgramClient, AgentWebSocketEvents, AgentKeepAlive
from deepgram.clients.agent.v1.websocket.options import SettingsOptions

# Env vars
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
SIP_USER = 'VAg'
SIP_PASS = 'pass123'  # Simple password; change if AT requires
SIP_DOMAIN = '159.69.88.217'  # Your VPS IP
SIP_PORT = 5060

# Queues for audio (SIP <-> Deepgram)
audio_in_queue = asyncio.Queue()  # SIP to Deepgram
audio_out_queue = asyncio.Queue()  # Deepgram to SIP

class AudioCallback(CallMediaTransport):
    def __init__(self, queue_in, queue_out):
        CallMediaTransport.__init__(self)
        self.queue_in = queue_in
        self.queue_out = queue_out

    def on_rx_event(self, med_idx, evt_type, evt_data):
        if evt_type == PJMEDIA_RX_EVENT_PKT:
            payload = evt_data['pkt']  # RTP payload (mulaw bytes)
            self.queue_in.put_nowait(payload)  # To Deepgram

class MyAccount(Account):
    def onIncomingCall(self, prm):
        call = MyCall(self, prm)
        self.cb = AudioCallback(audio_in_queue, audio_out_queue)
        call.media[0].transport = self.cb
        call.answer(200)
        print("SIP call answered—streaming to Deepgram!")

class MyCall(Call):
    def onState(self, prm):
        if self.info().state == PJSIP_INV_STATE_DISCONNECTED:
            print("Call disconnected.")

class MyApp(EpConf):
    def init(self):
        self.ep = Endpoint()
        self.ep.libCreate()
        self.ep.libInit(self)
        self.ep.libStart()

        # Transport
        tcfg = TransportConfig()
        self.ep.transportCreate(PJSIP_TRANSPORT_UDP, tcfg)

        # Account
        acfg = AccountConfig()
        acfg.idUri = f"sip:{SIP_USER}@{SIP_DOMAIN}"
        cred = AuthCredInfo("digest", "*", SIP_USER, 0, SIP_PASS)
        acfg.sipConfig.authCreds.append(cred)
        self.acc = MyAccount()
        self.ep.accAdd(self.acc, acfg)

    def start_deepgram(self):
        threading.Thread(target=self.deepgram_task, daemon=True).start()

    def deepgram_task(self):
        deepgram = DeepgramClient(DEEPGRAM_API_KEY)
        conn = deepgram.agent.v1.connect()

        # Options (mulaw/8kHz for SIP)
        options = SettingsOptions()
        options.audio.input.encoding = "mulaw"
        options.audio.input.sample_rate = 8000
        options.audio.output.encoding = "mulaw"
        options.audio.output.sample_rate = 8000
        options.audio.output.container = "none"
        options.agent.language = "en"
        options.agent.listen.provider.type = "deepgram"
        options.agent.listen.provider.model = "nova-3"
        options.agent.think.provider.type = "open_ai"
        options.agent.think.provider.model = "anthropic/claude-3.5-sonnet"
        options.agent.think.endpoint = "https://openrouter.ai/api/v1/chat/completions"
        options.agent.think.headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
        options.agent.think.prompt = "You are a friendly phone assistant. Respond concisely."
        options.agent.speak.provider.type = "deepgram"
        options.agent.speak.provider.model = "aura-2-thalia-en"
        options.agent.greeting = "Hello! How can I help you today?"

        # Events
        def on_audio_data(_, data, **kwargs):
            print(f"TTS chunk: {len(data)} bytes")
            audio_out_queue.put_nowait(data)  # To SIP

        def on_conversation_text(_, text, **kwargs):
            print(f"Transcript: {text}")

        def on_error(_, error, **kwargs):
            print(f"Deepgram error: {error}")

        conn.on(AgentWebSocketEvents.AudioData, on_audio_data)
        conn.on(AgentWebSocketEvents.ConversationText, on_conversation_text)
        conn.on(AgentWebSocketEvents.Error, on_error)

        # Start
        conn.start(options)
        print("Deepgram agent started!")

        # Stream loop (SIP to Deepgram)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(stream_to_deepgram(conn))

    async def stream_to_deepgram(self, conn):
        while True:
            if not audio_in_queue.empty():
                chunk = await audio_in_queue.get()
                conn.send(chunk)
            await asyncio.sleep(0.02)

    def run(self):
        self.init()
        self.start_deepgram()
        print(f"SIP bridge listening on {SIP_DOMAIN}:{SIP_PORT}")
        self.ep.libHandleEvents(0)  # Event loop

if __name__ == '__main__':
    app = MyApp()
    app.run()
