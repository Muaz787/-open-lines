/* ─────────────────────────────────────────────────────────────
   Learn / guide content — one object per informational article.
   Top-of-funnel pages: each targets a distinct search intent with
   genuinely useful, standalone content. Drives /learn/[slug] + hub.
   ───────────────────────────────────────────────────────────── */

export interface LearnArticle {
  slug: string
  category: string
  shortTitle: string
  metaTitle: string
  metaDescription: string
  h1: string
  updated: string
  intro: string
  sections: { heading: string; paras?: string[]; bullets?: { title: string; body: string }[] }[]
  faqs: { q: string; a: string }[]
  ctaHeading: string
  ctaSub: string
}

export const ARTICLES: LearnArticle[] = [
  {
    slug: 'answering-service-cost',
    category: 'Cost guide',
    shortTitle: 'Answering service cost',
    metaTitle: 'How Much Does an Answering Service Cost in 2026? — Open Lines',
    metaDescription: 'A clear 2026 breakdown of answering service costs — per-minute live services, in-house receptionists, and flat-rate AI receptionists — so you can pick what fits.',
    h1: 'How much does an answering service cost in 2026?',
    updated: '2026',
    intro: 'If you’re losing business to missed calls, an answering service is the obvious fix — but the pricing models are all over the map. Here’s a plain breakdown of what each option really costs in 2026, and how to work out which one is cheapest for the volume of calls you actually get.',
    sections: [
      {
        heading: 'The three ways businesses cover their phone',
        paras: ['Broadly, there are three ways to make sure your calls get answered. They price very differently, and the “cheapest” one depends entirely on your call volume.'],
        bullets: [
          { title: 'Live (human) answering services', body: 'A call centre answers in your name. Usually billed per minute or in monthly minute bundles — great for overflow, but the meter is always running.' },
          { title: 'An in-house receptionist', body: 'A person on your payroll. Total coverage during their hours, but the highest fixed cost and no nights or weekends without paying overtime.' },
          { title: 'An AI receptionist', body: 'Software answers, books, and captures leads 24/7, typically for a flat monthly fee that doesn’t spike with call volume.' },
        ],
      },
      {
        heading: 'Typical 2026 price ranges',
        paras: [
          'Live answering services are commonly billed around $1–$2 per minute, or in monthly bundles that often land anywhere from roughly $200 to $600+ per month once you’re past a light plan. The catch is that costs scale directly with how much your callers talk — a few long calls can blow the budget.',
          'A full-time in-house receptionist typically runs $35,000–$50,000+ per year once you include wages, benefits, and overhead — and that still only covers business hours.',
          'An AI receptionist is usually a flat monthly subscription. Because it isn’t billed per minute, the cost stays predictable whether you get 20 calls a month or 200, and it covers nights, weekends, and holidays at no extra charge.',
        ],
      },
      {
        heading: 'How to work out your real cost',
        paras: ['Add up your monthly call volume and average call length. Multiply by the per-minute rate for a live service, and compare that to a flat AI subscription. For most appointment- and enquiry-driven small businesses, once you’re past a handful of calls a day, a flat rate wins on both price and coverage — and it never sends a caller to voicemail after hours.'],
      },
      {
        heading: 'Where Open Lines fits',
        paras: ['Open Lines is a flat-rate AI receptionist: it answers every call in a natural voice, books appointments into your calendar, captures leads, and works 24/7 — with no per-minute meter. You can compare plans on the pricing page and start a 7-day free trial with no credit card.'],
      },
    ],
    faqs: [
      { q: 'Is an AI receptionist cheaper than a live answering service?', a: 'For most small businesses past a few calls a day, yes. Live services bill per minute, so cost rises with call volume, while an AI receptionist is a flat monthly fee that also covers nights and weekends.' },
      { q: 'Are there per-minute or per-call fees with Open Lines?', a: 'Open Lines is a flat monthly subscription rather than a per-minute meter, so your cost stays predictable regardless of how busy the phone gets. See the pricing page for current plans.' },
      { q: 'What does a full-time receptionist cost?', a: 'Typically $35,000–$50,000+ per year once wages, benefits, and overhead are included — and that only covers their working hours, not after-hours or weekend calls.' },
      { q: 'Can I try it before paying?', a: 'Yes. Open Lines offers a 7-day free trial with no credit card, so you can see how it handles your calls before committing.' },
    ],
    ctaHeading: 'Predictable pricing. Every call answered.',
    ctaSub: 'Start a 7-day free trial and see what a flat-rate AI receptionist does for your missed calls.',
  },
  {
    slug: 'what-is-an-ai-receptionist',
    category: 'Basics',
    shortTitle: 'What is an AI receptionist',
    metaTitle: 'What Is an AI Receptionist? A 2026 Guide — Open Lines',
    metaDescription: 'What an AI receptionist is, how it answers calls and books appointments, what it can and can’t do, and which businesses benefit most. A plain-English 2026 guide.',
    h1: 'What is an AI receptionist?',
    updated: '2026',
    intro: 'An AI receptionist is software that answers your phone in a natural voice, has a real conversation with the caller, and handles the things a front-desk receptionist would — booking appointments, answering common questions, and taking down leads — 24 hours a day. Here’s how it actually works and where it fits.',
    sections: [
      {
        heading: 'How it works, step by step',
        bullets: [
          { title: '1. It answers the call', body: 'When your line rings, the AI picks up in a warm, human-sounding voice and greets the caller in your business’s name.' },
          { title: '2. It understands what they want', body: 'It listens, understands natural speech, and responds in real time — booking, answering a question, or taking a message.' },
          { title: '3. It acts', body: 'It checks your live calendar and books the appointment, captures the caller’s details, or flags an urgent matter for a callback.' },
          { title: '4. It reports back', body: 'You get a clean summary of every call — who called, what they needed, and the suggested next step — by email, text, Slack, or your CRM.' },
        ],
      },
      {
        heading: 'What a good AI receptionist can do',
        bullets: [
          { title: 'Book appointments', body: 'Reads real availability from Google Calendar, Outlook, or Square Appointments and books confirmed times.' },
          { title: 'Answer FAQs', body: 'Learns your hours, services, pricing, and policies from your own website and documents, and answers instantly.' },
          { title: 'Capture and qualify leads', body: 'Takes the caller’s details, screens the enquiry, and marks urgent ones so nothing slips.' },
          { title: 'Work around the clock', body: 'Covers nights, weekends, holidays, and busy periods when no one can pick up.' },
        ],
      },
      {
        heading: 'What it won’t do',
        paras: ['A responsible AI receptionist stays in its lane. It won’t invent answers it doesn’t know — instead it captures the question and routes it to you. It discloses that it’s a virtual assistant, and for regulated fields it handles intake and scheduling only, never professional advice. Anything it can’t confidently handle becomes a flagged message for a human.'],
      },
      {
        heading: 'Who benefits most',
        paras: ['Any business where a missed call is lost revenue: salons and barbershops, home services and trades, contractors, restaurants, real estate, auto shops, insurance brokers, and courier companies. If your team can’t always reach the phone and callers won’t leave a voicemail, an AI receptionist pays for itself in recovered bookings.'],
      },
    ],
    faqs: [
      { q: 'Does an AI receptionist sound robotic?', a: 'Modern AI receptionists like Open Lines use a natural, human-sounding voice. Callers rarely realise it’s AI — and it always discloses that it’s a virtual assistant, as required.' },
      { q: 'Can it actually book appointments?', a: 'Yes. It reads your real calendar availability (Google, Outlook, or Square Appointments) and books confirmed appointments, so there’s no double-booking or manual follow-up.' },
      { q: 'What happens if it can’t answer something?', a: 'It doesn’t guess. It captures the caller’s question and details and routes them to you for follow-up, so nothing is lost.' },
      { q: 'How long does it take to set up?', a: 'With Open Lines, most businesses are live in under 10 minutes — it learns from your website, so there’s little to configure.' },
    ],
    ctaHeading: 'See what an AI receptionist does for you.',
    ctaSub: 'Start a 7-day free trial — no credit card — and let it answer your next call.',
  },
  {
    slug: 'missed-call-text-back',
    category: 'Guide',
    shortTitle: 'Missed-call text-back',
    metaTitle: 'Missed-Call Text-Back: Turn Missed Calls Into Booked Jobs — Open Lines',
    metaDescription: 'What missed-call text-back is, why missed calls quietly cost you revenue, and how answering live then confirming by text wins more bookings. A 2026 guide.',
    h1: 'Missed-call text-back — and why answering live is even better',
    updated: '2026',
    intro: 'Missed-call text-back automatically sends a text to anyone whose call you didn’t answer. It’s a smart safety net — but the real win is not missing the call in the first place. Here’s how both approaches work and how to capture the business you’re currently losing to voicemail.',
    sections: [
      {
        heading: 'Why missed calls quietly cost you money',
        paras: [
          'Most callers who reach voicemail simply hang up and call the next business on the list. They don’t leave a message and they don’t call back. For appointment- and enquiry-driven businesses, every unanswered call is often a booking handed straight to a competitor.',
          'The calls you miss cluster at the worst times: when you’re with a customer, on a job, or closed for the evening — exactly when you can’t drop everything to answer.',
        ],
      },
      {
        heading: 'What missed-call text-back does',
        paras: ['When a call goes unanswered, an automatic text goes out — usually something like “Sorry we missed you, how can we help?” It keeps the conversation alive and gives the caller an easy way back. It’s far better than silence, but it still starts from a missed call, and a text is easy for a busy caller to ignore.'],
      },
      {
        heading: 'The stronger play: answer live, then confirm by text',
        paras: ['Instead of missing the call and chasing it with a text, an AI receptionist answers it live — books the appointment or captures the lead in the moment — and then texts a confirmation. The caller gets what they wanted on the spot, and you get the booking rather than a maybe.'],
        bullets: [
          { title: 'Answered in seconds', body: 'The AI picks up on the first ring, 24/7, so the call is handled before it ever becomes a “missed call”.' },
          { title: 'Booked in the moment', body: 'It checks your calendar and books the appointment live, instead of hoping the caller replies to a text later.' },
          { title: 'Confirmed by text', body: 'The caller gets a clear confirmation by text, and you get a summary of the call — nothing left hanging.' },
        ],
      },
      {
        heading: 'How Open Lines handles it',
        paras: ['Open Lines answers every call live in a natural voice, books into your calendar, and then texts the caller a confirmation while sending you a summary. You capture the booking at its most valuable moment — during the call — instead of relying on a follow-up text to win it back.'],
      },
    ],
    faqs: [
      { q: 'Is missed-call text-back enough on its own?', a: 'It’s a helpful safety net, but it still begins with a missed call — and a text is easy to ignore. Answering the call live and booking in the moment captures far more of the business, then confirms by text.' },
      { q: 'Does Open Lines text the caller?', a: 'Yes. After it answers and books the call live, it texts the caller a confirmation and sends you a summary, so both sides have a record.' },
      { q: 'Why do missed calls cost so much?', a: 'Most callers who hit voicemail don’t leave a message — they call the next business. For booking-driven businesses, an unanswered call is usually a lost sale.' },
      { q: 'When do most missed calls happen?', a: 'When you’re busy with a customer or job, and after hours. An AI receptionist covers exactly those moments, 24/7.' },
    ],
    ctaHeading: 'Stop missing the calls that matter.',
    ctaSub: 'Start a 7-day free trial and let your AI receptionist answer, book, and confirm — automatically.',
  },
  {
    slug: 'virtual-receptionist-small-business',
    category: 'Guide',
    shortTitle: 'Virtual receptionist guide',
    metaTitle: 'Virtual Receptionists for Small Business: A 2026 Guide — Open Lines',
    metaDescription: 'The small-business guide to virtual receptionists in 2026 — the options, pros and cons, costs, and how to choose between a live service and an AI receptionist.',
    h1: 'The small business guide to virtual receptionists',
    updated: '2026',
    intro: 'A virtual receptionist answers your calls without sitting at your front desk. For a small business, it can be the difference between catching every lead and quietly losing them to voicemail. Here’s how the options compare and how to choose the right one for your business in 2026.',
    sections: [
      {
        heading: 'The two main types',
        bullets: [
          { title: 'Live virtual receptionists', body: 'Remote humans answer in your name, usually billed per minute or in monthly minute bundles. Personable, good for nuanced calls — but the cost scales with volume and coverage.' },
          { title: 'AI virtual receptionists', body: 'Software answers, books, and captures leads in a natural voice, 24/7, for a flat monthly fee. Consistent and always available, with no per-minute meter.' },
        ],
      },
      {
        heading: 'What to look for',
        bullets: [
          { title: 'Real calendar booking', body: 'It should read your live availability and book confirmed appointments — not just take messages.' },
          { title: '24/7 coverage', body: 'Nights and weekends are when many bookings happen. Make sure after-hours calls are actually answered.' },
          { title: 'Learns your business', body: 'It should answer your real FAQs — hours, services, pricing, location — from your own website and documents.' },
          { title: 'Clear reporting', body: 'You want a clean summary of every call, ideally synced to your CRM, Slack, or inbox.' },
          { title: 'Predictable pricing', body: 'Watch for per-minute costs that spike on your busiest months. A flat fee is easier to plan around.' },
        ],
      },
      {
        heading: 'How to choose',
        paras: ['If you get a low volume of complex, high-touch calls, a live service may suit you. If you get a steady stream of bookings and enquiries — and you’re losing some to voicemail — a flat-rate AI receptionist usually delivers better coverage for less, and never closes for the night. Many businesses start with an AI receptionist for the bulk of calls and keep escalation to a human for anything unusual.'],
      },
      {
        heading: 'Getting started with Open Lines',
        paras: ['Open Lines is an AI virtual receptionist built for local, appointment-driven businesses. It learns from your website, books into Google Calendar, Outlook, or Square Appointments, and reports every call to your inbox, Slack, or HubSpot. Setup takes under 10 minutes and there’s a 7-day free trial with no credit card.'],
      },
    ],
    faqs: [
      { q: 'What does a virtual receptionist do?', a: 'It answers your calls without being physically at your desk — booking appointments, answering common questions, and capturing leads. It can be a live remote person or an AI receptionist.' },
      { q: 'Is a virtual receptionist worth it for a small business?', a: 'If you’re losing calls to voicemail while you’re busy or closed, yes. Recovered bookings usually cover the cost quickly, especially with a flat-rate AI option.' },
      { q: 'Live receptionist or AI — which is better?', a: 'AI wins on 24/7 coverage and predictable flat pricing; a live service can suit low volumes of complex calls. Many businesses use AI for most calls and escalate unusual ones to a human.' },
      { q: 'How quickly can I get set up?', a: 'With Open Lines, most businesses are live in under 10 minutes because it learns from your existing website.' },
    ],
    ctaHeading: 'Give your small business a receptionist that never clocks out.',
    ctaSub: 'Start a 7-day free trial — no credit card — and let it answer every call.',
  },
  {
    slug: 'automate-your-workflow-2026-ai',
    category: 'Guide',
    shortTitle: 'Automate your workflow with AI',
    metaTitle: 'How to Automate Your Workflow in 2026 with AI (Tools + Tips) — Open Lines',
    metaDescription: 'A practical 2026 guide to automating your business workflow with AI — the tools worth using for calls, scheduling, CRM, payments, and comms, plus tips to start small.',
    h1: 'How to automate your workflow in 2026 using AI',
    updated: '2026',
    intro: 'Automation in 2026 isn’t about replacing your team — it’s about handing the repetitive, time-eating tasks to software so your people can do the work that actually needs a human. This guide walks through where AI genuinely helps, the tools worth using in each area, and how to start without over-engineering.',
    sections: [
      {
        heading: 'Start with the tasks that repeat',
        paras: ['The best automation targets are the tasks you do the same way, over and over: answering the same phone questions, booking appointments, chasing no-shows, copying call notes into a CRM, sending confirmations. Before buying any tool, list the five things your team does most often that follow a predictable pattern. Those are your first automations.'],
      },
      {
        heading: 'Automate your phone and reception',
        paras: ['For most local and service businesses, the phone is the single biggest source of missed revenue and repetitive work. An AI receptionist answers every call in a natural voice, books appointments into your calendar, answers your FAQs from your own website, and sends you a summary — 24/7.'],
        bullets: [
          { title: 'Open Lines', body: 'An AI receptionist that answers calls, books into Google Calendar, Outlook, or Square Appointments, captures leads, and reports each call to your inbox, Slack, or HubSpot. Flat monthly pricing, live in under 10 minutes.' },
        ],
      },
      {
        heading: 'Automate scheduling and reminders',
        paras: ['Cut the back-and-forth of booking by letting people self-schedule against your real availability, and reduce no-shows with automatic reminders.'],
        bullets: [
          { title: 'Google Calendar / Outlook', body: 'The backbone most tools book into. Keep one source of truth for availability so nothing double-books.' },
          { title: 'Calendly (and similar)', body: 'Lets clients pick a time from your live availability without emailing back and forth.' },
          { title: 'Automatic reminders + deposits', body: 'Confirmation and reminder messages — and a deposit at booking (e.g. via Stripe) — dramatically cut no-shows.' },
        ],
      },
      {
        heading: 'Automate your CRM and follow-up',
        paras: ['The notes that never get typed up are the leads that never get followed up. Push call and enquiry data into your CRM automatically so follow-up is fast and nothing slips.'],
        bullets: [
          { title: 'HubSpot', body: 'A widely used CRM for small business. Tools like Open Lines can create the contact and attach an AI call summary automatically after every call.' },
          { title: 'Automation platforms', body: 'General-purpose “glue” tools (such as Make or Zapier) can connect apps that don’t natively talk to each other — useful once you outgrow built-in integrations.' },
        ],
      },
      {
        heading: 'Automate payments and team comms',
        bullets: [
          { title: 'Stripe / Square', body: 'Collect deposits and payments with a secure link instead of chasing invoices — and protect your calendar from no-shows.' },
          { title: 'Slack', body: 'Route automatic updates — like a message after every call — to the right channel so the team stays in the loop without extra meetings.' },
        ],
      },
      {
        heading: 'Use AI assistants for the writing',
        paras: ['General AI assistants like ChatGPT and Claude are excellent for drafting emails, summarising documents, writing first drafts, and answering one-off questions. Treat them as a fast first draft you review — not a final authority — and never paste in sensitive customer data you wouldn’t want stored.'],
      },
      {
        heading: 'Five tips to automate without regret',
        bullets: [
          { title: 'Start with one workflow', body: 'Automate a single high-volume task end to end before adding more. One win beats ten half-finished experiments.' },
          { title: 'Keep a human in the loop', body: 'Let automation handle the routine and escalate anything unusual to a person. Good tools flag what they can’t handle.' },
          { title: 'Keep one source of truth', body: 'Pick one calendar and one CRM. Automation multiplies mess as fast as it multiplies order.' },
          { title: 'Measure the time saved', body: 'Track hours recovered or bookings gained so you know which automations actually earn their keep.' },
          { title: 'Mind privacy and disclosure', body: 'Be transparent when customers interact with AI, and don’t feed confidential data into tools that store it.' },
        ],
      },
      {
        heading: 'A simple starting stack',
        paras: ['If you run a local or service business and want one place to begin: put an AI receptionist on your phone so no call is missed, connect it to your calendar so bookings are automatic, and route summaries to your CRM or Slack so follow-up runs itself. That single chain — call → booking → follow-up — is where most small businesses recover the most time and revenue. Open Lines is built to be exactly that first link, and you can try it free for 7 days.'],
      },
    ],
    faqs: [
      { q: 'What’s the easiest business workflow to automate first?', a: 'Usually the phone. Answering, booking, and logging calls is high-volume and highly repetitive, so an AI receptionist tends to deliver the fastest, most visible win.' },
      { q: 'Do I need technical skills to automate my workflow?', a: 'Not for the essentials. Tools like Open Lines learn from your website and go live in minutes. You only need “glue” platforms once you’re connecting several custom systems.' },
      { q: 'Will automating make my business feel impersonal?', a: 'It shouldn’t. Good automation handles the repetitive parts so your team has more time for the human moments — and quality AI discloses itself and escalates anything unusual to a person.' },
      { q: 'Where does Open Lines fit in an automated workflow?', a: 'It automates the first and most valuable link: answering the phone, booking into your calendar, and pushing a summary to your CRM or Slack — so the call-to-booking-to-follow-up chain runs itself.' },
    ],
    ctaHeading: 'Automate the one workflow that pays for itself first.',
    ctaSub: 'Put an AI receptionist on your phone in under 10 minutes. Start a 7-day free trial — no credit card.',
  },
]

export const ARTICLE_SLUGS = ARTICLES.map(a => a.slug)

export function getArticle(slug: string): LearnArticle | undefined {
  return ARTICLES.find(a => a.slug === slug)
}
