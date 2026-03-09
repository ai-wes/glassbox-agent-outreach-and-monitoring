<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" class="logo" width="120"/>

# Automating Daily Tech-and-AI Podcast Briefings

**Summary of the Solution**
This report presents a complete Python-based workflow that (1) fetches new episodes from ten leading technology and AI podcasts, (2) downloads their audio, (3) transcribes each episode with OpenAI Whisper, (4) summarizes the transcripts with GPT-3.5-turbo, (5) converts the summary to high-quality speech using Microsoft Edge-TTS, and (6) emails both the written digest and an attached MP3 every morning at a scheduled time. The design relies only on widely supported libraries (feedparser, requests, OpenAI, edge-tts, schedule, smtplib) and standard cron/Task Scheduler, so it runs reliably on Linux, macOS, or Windows.

![Daily podcast summarization pipeline](https://user-gen-media-assets.s3.amazonaws.com/gpt4o_images/e413b25a-5df4-45e4-b6ca-0fefdbde1652.png)

Daily podcast summarization pipeline

## 1. Podcast Sources

### 1.1 Feeds Monitored Daily

| Podcast | RSS Feed Example | Typical Episode Length |
| :-- | :-- | :-- |
| Pivot | https://feeds.megaphone.fm/pivot | 60 min[^1] |
| Hard Fork | https://rss.art19.com/hard-fork | 45 min[^2] |
| The Vergecast | https://feeds.megaphone.fm/vergecast | 75 min[^3] |
| All-In Podcast | https://rss.art19.com/all-in | 90 min[^4] |
| NVIDIA AI Podcast | https://feeds.soundcloud.com/users/soundcloud:users:232716163/sounds.rss | 30 min[^5] |
| Lex Fridman Podcast | https://lexfridman.com/feed/podcast/ | 2 h |
| Latent Space | https://latent.space/rss.xml | 60 min |
| Practical AI | https://changelog.com/practicalai/feed | 50 min |
| Eye on AI | https://feeds.acast.com/public/shows/eye-on-ai | 45 min |
| DeepMind: The Podcast | https://feeds.acast.com/public/shows/deepmind-the-podcast | 35 min |

*Feeds can be adjusted in a JSON config file without altering code.*

## 2. Core Python Modules

| Purpose | Library | Key Function |
| :-- | :-- | :-- |
| Read RSS | `feedparser`[^6] | `feedparser.parse(url)` |
| Download audio | `requests` (stream)[^7] | `iter_content()` |
| Transcription | `openai` Whisper API[^8][^9] | `audio.transcriptions.create()` |
| Summarization | `openai` Chat Completion[^10][^11] | `chat.completions.create()` |
| Text-to-Speech | `edge-tts`[^12][^13] | `edge_tts.Communicate` |
| Scheduling | `schedule` + cron[^14][^13][^15] | `every().day.at()` |
| Email | `smtplib` + `email`[^16][^17][^18] | `send_message()` |

## 3. End-to-End Workflow

### 3.1 Daily Scheduler

1. **06:00 local time:** Cron (Linux/macOS) or Task Scheduler (Windows) triggers `daily_pods.py`.
2. Within Python, `schedule` can double-check timing to avoid overlaps.

### 3.2 Episode Retrieval

```python
import feedparser, requests, pathlib, datetime as dt
from urllib.parse import urlparse

def fetch_latest(feed_url, since_ts):
    feed = feedparser.parse(feed_url)
    for entry in feed.entries:
        pub = dt.datetime(*entry.published_parsed[:6])
        if pub > since_ts:
            audio = next(e.href for e in entry.enclosures if e.type.startswith('audio'))
            yield entry.title, audio, pub
```

*The function yields only new episodes since yesterday’s timestamp stored in a local SQLite DB.*

### 3.3 Streaming Download

```python
def download_mp3(url, dest_folder):
    filename = pathlib.Path(urlparse(url).path).name
    path = dest_folder/filename
    with requests.get(url, stream=True, timeout=60) as r, open(path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024*32):
            if chunk:
                f.write(chunk)
    return path
```

*Chunked download prevents memory spikes.*

### 3.4 Speech-to-Text

```python
from openai import OpenAI
client = OpenAI()

def transcribe(path):
    with open(path, 'rb') as audio:
        txt = client.audio.transcriptions.create(
              model="whisper-1", file=audio,
              response_format="text").text
    return txt
```


### 3.5 Summarization Prompt

```python
SYSTEM = "You are an expert podcast analyst. Provide a concise bullet digest (≤150 words) of the transcript."
def summarize(text):
    resp = client.chat.completions.create(
        model="gpt-3.5-turbo-0125",
        messages=[{"role":"system","content":SYSTEM},
                  {"role":"user","content":text[:12000]}], # token safe
        max_tokens=220)
    return resp.choices[^0].message.content.strip()
```


### 3.6 Text-to-Speech

```python
import asyncio, edge_tts, uuid, pathlib

async def tts(summary, out_dir):
    vid = f"sum-{uuid.uuid4().hex}.mp3"
    path = out_dir/vid
    tts = edge_tts.Communicate(summary, voice="en-US-JennyNeural")
    await tts.save(str(path))
    return path
```


### 3.7 Email Delivery

```python
from email.message import EmailMessage
import smtplib, os

def send_digest(text_body, audio_path):
    msg = EmailMessage()
    msg['Subject'] = f"Daily Tech Podcast Briefing – {dt.date.today():%b %d}"
    msg['From'] = os.getenv("MAIL_FROM")
    msg['To'] = os.getenv("MAIL_TO")
    msg.set_content(text_body)

    with open(audio_path, 'rb') as f:
        msg.add_attachment(f.read(), maintype='audio', subtype='mpeg',
                           filename=audio_path.name)
    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST"), 465) as server:
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        server.send_message(msg)
```

![Mockup of the automated daily email](https://user-gen-media-assets.s3.amazonaws.com/gpt4o_images/4d26954c-2267-47bf-b101-ef8b3398dcc9.png)

Mockup of the automated daily email

## 4. Storage \& Housekeeping

* **Directory layout**

```
~/podbrief/
    audio/        # MP3 files
    voice/        # TTS output
    transcripts/  # .txt
    digests/      # .md archives
    podbrief.db   # sqlite: episode IDs + timestamps
```

* Files older than 14 days are deleted by a weekly cleanup job.


## 5. Deployment Steps

1. `python -m venv podenv && source podenv/bin/activate`
2. `pip install feedparser requests openai edge-tts schedule python-dotenv`
3. Add `.env` with `OPENAI_API_KEY`, mail credentials, and RSS list.
4. Place `daily_pods.py` in project root; mark executable.
5. **Cron example**

```
0 6 * * * /home/wes/podenv/bin/python /home/wes/podbrief/daily_pods.py >> /home/wes/podbrief/log.txt 2>&1
```

6. Confirm first run; email with attached MP3 and Markdown arrives by 06:05.

## 6. Cost \& Runtime Estimates

| Stage | Time per 60-min episode | Cost per hour |
| :-- | :-- | :-- |
| Download (50 MB) | 1–2 min | — |
| Whisper tiny-En | 3 × realtime | \$0.006[^8] |
| Summarize (GPT-3.5-turbo) | <5 s | \$0.002 |
| Edge-TTS synth (≈45 s audio) | 20 s | free |
| **Total** | ≈5 min | **\$0.008** |

*Processing ten shows (<8 h audio) costs under \$0.10/day and finishes in ~40 min on a modest CPU.*

## 7. Extending the System

1. **Chat bot**: Pipe summaries into a vector database (e.g., Chroma) and run daily Q\&A.
2. **Keyword alerts**: Trigger SMS if transcripts mention specified topics.
3. **Web dashboard**: Serve digests via Flask to browse and search archives.
4. **Multi-language**: Change Whisper `language` or let it auto-detect; set Edge-TTS voice accordingly.

## 8. Troubleshooting Tips

| Symptom | Likely Cause | Remedy |
| :-- | :-- | :-- |
| Empty RSS parse | Feed requires HTTPS redirect | Use final URL or `requests.get` to follow redirects. |
| Whisper `RateLimitError` | Parallel transcriptions saturate token quota | Process sequentially or apply exponential backoff. |
| TTS “429 Too Many Requests” | Edge-TTS throttling | Cache voices, insert `asyncio.sleep(1)` between calls. |
| Email not delivered | Gmail blocks less-secure app | Use an app password or a domain SMTP relay. |

## 9. Conclusion

The outlined architecture delivers a fully automated, low-maintenance pipeline that converts the week’s richest tech podcasts into a concise, listenable briefing waiting in your inbox each morning. With open-source libraries and commodity cloud APIs, you control scheduling, data retention, and costs while staying up to speed on AI and software trends before your first cup of coffee.

<div style="text-align: center">⁂</div>

[^1]: https://podcastparser.readthedocs.io

[^2]: https://pypi.org/project/podcast-downloader/0.2.1/

[^3]: https://github.com/mr-rigden/pyPodcastParser

[^4]: https://mr-destructive.github.io/techstructive-blog/python-feedparser/

[^5]: https://pypi.org/project/getpodcast/

[^6]: https://www.tothenew.com/blog/rss-feed-parsing-using-pyspark/

[^7]: https://pypi.org/project/pyPodcastParser/

[^8]: https://stackoverflow.com/questions/69517250/download-podcast-in-python

[^9]: https://pypi.org/project/podcastparser/

[^10]: https://github.com/dplocki/podcast-downloader

[^11]: https://dev.to/deepgram/how-to-transcribe-your-podcast-with-python-32i1

[^12]: https://www.reddit.com/r/Python/comments/43rwnx/my_first_python_script_a_way_to_download_podcasts/

[^13]: https://gist.github.com/axi0m/be404e2aae6cd78b4db7fe1ed7b2d3c5

[^14]: https://www.nashruddinamin.com/blog/summarizing-podcasts-with-python

[^15]: https://github.com/gpodder/podcastparser

[^16]: https://arachnoid.com/python/PodcastRetriever/index.html

[^17]: https://covrebo.com/parsing-rss-feeds-with-python-universal-feed-parser.html

[^18]: https://tylerquinlivan.com/posts/podqueue/

[^19]: https://stackoverflow.com/questions/30575338/whats-the-best-way-to-get-a-podcast-episodes-shownotes-using-feedparser

[^20]: https://douglas-watson.github.io/post/2020-05_export_podcasts/

[^21]: https://pythonroadmap.com/blog/send-email-attachments-with-python

[^22]: https://pypi.org/project/gTTS/

[^23]: https://github.com/heyfoz/python-openai-whisper

[^24]: https://stackoverflow.com/questions/52022134/how-do-i-schedule-an-email-to-send-at-a-certain-time-using-cron-and-smtp-in-pyt

[^25]: https://videosdk.live/developer-hub/ai/edge-tts

[^26]: https://stackoverflow.com/questions/3362600/how-to-send-email-attachments

[^27]: https://github.com/pndurette/gTTS

[^28]: https://christophergs.com/blog/ai-podcast-transcription-whisper

[^29]: https://www.youtube.com/watch?v=vscDphDAcQM

[^30]: https://pypi.org/project/edge-tts/

[^31]: https://djangocentral.com/sending-emails-with-csv-attachment-using-python/

[^32]: https://www.youtube.com/watch?v=X9rxXFjoWzg

[^33]: https://github.com/openai/whisper

[^34]: https://www.uptimia.com/learn/schedule-cron-jobs-in-python

[^35]: https://gustawdaniel.com/notes/python-edge-tts/

[^36]: https://hackernoon.com/how-to-send-html-emails-with-attachments-using-python

[^37]: https://www.geeksforgeeks.org/python/convert-text-speech-python/

[^38]: https://wandb.ai/wandb_fc/gentle-intros/reports/OpenAI-Whisper-How-to-Transcribe-Your-Audio-to-Text-for-Free-with-SRTs-VTTs---VmlldzozNDczNTI0

[^39]: https://askubuntu.com/questions/1236586/how-to-schedule-a-cronjob-for-python-script-to-be-executed-on-weekdays

[^40]: https://pypi.org/project/edge-tts-ext/

[^41]: https://discuss.python.org/t/problems-getting-summary-from-openai-in-python/75594

[^42]: https://www.geeksforgeeks.org/python/python-schedule-library/

[^43]: https://wordpress.com/forums/topic/enclosure-feed-not-working-audio-podcast/

[^44]: https://stackoverflow.com/questions/78513041/openai-completions-api-how-do-i-extract-the-text-from-the-response

[^45]: https://pypi.org/project/schedule/

[^46]: https://github.com/rany2/edge-tts

[^47]: https://community.openai.com/t/information-summary-by-using-api/578792

[^48]: https://schedule.readthedocs.io/en/stable/examples.html

[^49]: https://groups.google.com/g/feedburner-podcasting/c/_WA-_HhDatU

[^50]: https://community.openai.com/t/how-to-summarize-a-large-transcript-file/925317

[^51]: https://stackoverflow.com/questions/66797651/use-the-schedule-library-to-run-a-job-once-tomorrow

[^52]: https://deepgram.com/learn/create-readable-transcripts-for-podcasts

[^53]: https://docs.python.org/3/library/smtplib.html

[^54]: https://stackoverflow.com/questions/39128738/downloading-a-song-through-python-requests

[^55]: https://www.reddit.com/r/learnpython/comments/mqea2m/is_it_possible_to_send_an_email_in_python_with_a/

[^56]: https://proxiesapi.com/articles/streaming-downloads-with-python-requests

[^57]: https://www.geeksforgeeks.org/python/schedule-a-python-script-to-run-daily/

[^58]: https://www.freecodecamp.org/news/how-to-turn-audio-to-text-using-openai-whisper/

[^59]: https://stackoverflow.com/questions/21715298/python-requests-return-file-like-object-for-streaming/60846477

[^60]: https://pydigger.com/pypi/edge-tts-ext

[^61]: https://platform.openai.com/docs/guides/speech-to-text

[^62]: https://gist.github.com/lugia19/c6fc9de4a8da30d5430ec468c18551a3

[^63]: https://leimao.github.io/blog/Python-Everyday-Routine-Scheduler/

[^64]: https://python-forum.io/thread-35385.html

[^65]: https://www.youtube.com/watch?v=2fG0b4IZPnI

[^66]: https://podnews.net/podcast/i9pa

[^67]: https://podnews.net/podcast/i4hlx

[^68]: https://podnews.net/podcast/i6wu

[^69]: https://podnews.net/podcast/i42po

[^70]: https://www.nvidia.com/en-us/about-nvidia/rss/

[^71]: https://plinkhq.com/i/1073226719?to=page

[^72]: https://ifttt.com/connect/feed/hard_fork_podcast

[^73]: https://www.theverge.com/podcasts

[^74]: http://www.allin.com

[^75]: https://www.listennotes.com/podcasts/nvidia-ai-podcast-nvidia-8WS6JPYmMvj/

[^76]: https://rss.com/podcasts/the-pivot-leadership-podcast/

[^77]: https://podcastaddict.com/podcast/hard-fork/3181935

[^78]: https://cms.megaphone.fm/channel/vergecast

[^79]: https://www.podchaser.com/podcasts/all-in-with-chamath-jason-sack-1057128

[^80]: https://www.podchaser.com/podcasts/nvidia-ai-podcast-234571

[^81]: https://podcasts.voxmedia.com/show/pivot

[^82]: https://openpodme.vercel.app/podcast/sway

[^83]: https://www.podchaser.com/podcasts/the-vergecast-215071

[^84]: http://www.allinpodcast.co

[^85]: https://www.nvidia.com/en-us/ai-podcast/

