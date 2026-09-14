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
  /** ISO dates for E-E-A-T + Article schema. */
  published: string
  updated: string
  intro: string
  /** Optional editorial-methodology note (e.g. how figures were researched). */
  methodology?: string
  sections: { heading: string; paras?: string[]; bullets?: { title: string; body: string }[] }[]
  faqs: { q: string; a: string }[]
  /** Cited sources (shown as a references list + used in the methodology). */
  sources?: { label: string; url: string }[]
  /** Contextual internal links: related guides + one commercial page. */
  related: { href: string; label: string; sub?: string }[]
  ctaHeading: string
  ctaSub: string
}

export const ARTICLES: LearnArticle[] = [
  {
    slug: 'answering-service-cost',
    category: 'Cost guide',
    shortTitle: 'Answering service cost',
    metaTitle: 'Answering Service Cost: 2026 Guide | Open Lines',
    metaDescription: 'What answering services cost in 2026 — live per-minute services, in-house staff, and AI plans with included minutes — with real, cited figures.',
    h1: 'How much does an answering service cost in 2026?',
    published: '2026-07-28',
    updated: '2026-07-30',
    intro: 'If you’re losing business to missed calls, an answering service is the obvious fix — but the pricing models are all over the map. Here’s a plain breakdown of what each option really costs in 2026, with figures drawn from current published pricing, and how to work out which one is cheapest for the volume of calls you actually get.',
    methodology: 'Figures below reflect published 2026 pricing from several answering-service providers and salary data for Canada, gathered and last checked on July 30, 2026. Ranges are indicative — your exact cost depends on call volume, features, and provider. Sources are listed at the end.',
    sections: [
      {
        heading: 'The three ways businesses cover their phone',
        paras: ['Broadly, there are three ways to make sure your calls get answered. They price very differently, and the “cheapest” one depends entirely on your call volume.'],
        bullets: [
          { title: 'Live (human) answering services', body: 'A call centre answers in your name. Usually billed per minute or in monthly minute bundles — great for overflow, but the meter is always running.' },
          { title: 'An in-house receptionist', body: 'A person on your payroll. Total coverage during their hours, but the highest fixed cost and no nights or weekends without paying overtime.' },
          { title: 'An AI receptionist', body: 'Software answers, books, and captures leads 24/7, usually on a monthly plan that includes a set allowance of minutes, with a per-minute overage only if you exceed it.' },
        ],
      },
      {
        heading: 'Typical 2026 price ranges',
        paras: [
          'Live answering services in 2026 are commonly billed at roughly $0.75–$2.00 per minute, with many mid-range providers around $0.90–$1.25 per minute. On monthly bundles, basic plans tend to run about $135–$250, mid-range plans about $330–$525, and higher-volume plans about $495–$925 — and busy months can add 20–40% in overage fees on top. The catch is that cost scales directly with how much your callers talk.',
          'A full-time in-house receptionist in Canada typically costs around $40,000–$62,000 per year in wages (roughly $18–$20+ per hour), before you add benefits and overhead — and that still only covers business hours, not nights or weekends.',
          'An AI receptionist is usually a monthly plan with a set allowance of included minutes. Unlike a live service, you’re not metered from the very first minute — you get a block of minutes for your base fee, and only pay a per-minute overage if you go beyond it. It covers nights, weekends, and holidays at no extra charge.',
        ],
      },
      {
        heading: 'How to work out your real cost',
        paras: ['Add up your monthly call volume and average call length. Multiply by the per-minute rate for a live service, then compare that to an AI plan’s base fee plus its included minutes (and any overage beyond them). For most appointment- and enquiry-driven small businesses, once you’re past a handful of calls a day, an AI plan with a generous included allowance works out cheaper and covers hours a live meter would keep charging for — and it never sends a caller to voicemail after hours.'],
      },
      {
        heading: 'Where Open Lines fits',
        paras: ['Open Lines is an AI receptionist on a simple monthly plan: each plan includes a set number of minutes, with a per-minute overage rate only if you go over — and a call is never cut off mid-conversation. It answers every call in a natural voice, books appointments into your calendar, captures leads, and works 24/7. You can compare plans on the pricing page and start a 7-day free trial — cancel anytime before you’re charged.'],
      },
    ],
    faqs: [
      { q: 'Is an AI receptionist cheaper than a live answering service?', a: 'For most small businesses past a few calls a day, yes. Live services meter every minute from the start, so cost rises with call volume, while an AI plan gives you a block of included minutes for a monthly fee — with overage only beyond it — and covers nights and weekends.' },
      { q: 'Does Open Lines charge per minute?', a: 'Each Open Lines plan includes a set number of minutes for a flat monthly price. If you go over your included minutes, the extra time is billed at your plan’s per-minute overage rate — and calls are never cut off mid-conversation. See the pricing page for current plans and rates.' },
      { q: 'What does a full-time receptionist cost?', a: 'In Canada, receptionist wages typically run about $40,000–$62,000 per year (roughly $18–$20+ per hour) before benefits and overhead — and that only covers working hours, not after-hours or weekend calls.' },
      { q: 'Can I try it before paying?', a: 'Yes. Open Lines offers a 7-day free trial so you can see how it handles your calls before committing. You pick a plan and add a card up front, but nothing is charged until the trial ends, and you can cancel any time before then.' },
    ],
    sources: [
      { label: 'Housecall Pro — How Much Does an Answering Service Cost? (2026)', url: 'https://www.housecallpro.com/resources/how-much-does-an-answering-service-cost/' },
      { label: 'Nextiva — Answering Service Cost (2026)', url: 'https://www.nextiva.com/blog/answering-service-cost.html' },
      { label: 'NextPhone — Answering Service Cost Per Month (2026)', url: 'https://www.getnextphone.com/blog/phone-answering-costs' },
      { label: 'Talent.com — Receptionist average salary in Canada (2026)', url: 'https://ca.talent.com/salary?job=receptionist' },
      { label: 'PayScale — Receptionist hourly pay in Canada (2026)', url: 'https://www.payscale.com/research/CA/Job=Receptionist/Hourly_Rate' },
    ],
    related: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How AI phone answering actually works.' },
      { href: '/learn/virtual-receptionist-small-business', label: 'Virtual receptionist guide', sub: 'Live vs. AI, and how to choose.' },
      { href: '/pricing', label: 'See Open Lines pricing', sub: 'Monthly plans with included minutes.' },
    ],
    ctaHeading: 'Clear pricing. Every call answered.',
    ctaSub: 'Start a 7-day free trial and see what an AI receptionist does for your missed calls.',
  },
  {
    slug: 'what-is-an-ai-receptionist',
    category: 'Basics',
    shortTitle: 'What is an AI receptionist',
    metaTitle: 'What Is an AI Receptionist? A 2026 Guide — Open Lines',
    metaDescription: 'What an AI receptionist is, how it answers calls and books appointments, what it can and can’t do, and which businesses benefit most. A plain-English 2026 guide.',
    h1: 'What is an AI receptionist?',
    published: '2026-07-28',
    updated: '2026-07-30',
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
    related: [
      { href: '/learn/answering-service-cost', label: 'What does an answering service cost?', sub: '2026 pricing, compared.' },
      { href: '/learn/missed-call-text-back', label: 'Missed-call text-back', sub: 'Turn missed calls into booked jobs.' },
      { href: '/industries', label: 'See it for your industry', sub: 'Salons, trades, real estate, and more.' },
    ],
    ctaHeading: 'See what an AI receptionist does for you.',
    ctaSub: 'Start a 7-day free trial and let it answer your next call. Cancel anytime before you’re charged.',
  },
  {
    slug: 'missed-call-text-back',
    category: 'Guide',
    shortTitle: 'Missed-call text-back',
    metaTitle: 'Missed-Call Text-Back: 2026 Guide | Open Lines',
    metaDescription: 'What missed-call text-back is, why missed calls quietly cost you revenue, and how answering live then confirming by text wins more bookings. A 2026 guide.',
    h1: 'Missed-call text-back — and why answering live is even better',
    published: '2026-07-28',
    updated: '2026-07-30',
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
    related: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How it answers live and books.' },
      { href: '/learn/answering-service-cost', label: 'What does an answering service cost?', sub: '2026 pricing, compared.' },
      { href: '/realtors', label: 'AI receptionist for real estate', sub: 'Win the speed-to-lead race.' },
    ],
    ctaHeading: 'Stop missing the calls that matter.',
    ctaSub: 'Start a 7-day free trial and let your AI receptionist answer, book, and confirm — automatically.',
  },
  {
    slug: 'virtual-receptionist-small-business',
    category: 'Guide',
    shortTitle: 'Virtual receptionist guide',
    metaTitle: 'Virtual Receptionist for Small Business | Open Lines',
    metaDescription: 'The small-business guide to virtual receptionists in 2026 — the options, pros and cons, costs, and how to choose between a live service and an AI receptionist.',
    h1: 'The small business guide to virtual receptionists',
    published: '2026-07-28',
    updated: '2026-07-30',
    intro: 'A virtual receptionist answers your calls without sitting at your front desk. For a small business, it can be the difference between catching every lead and quietly losing them to voicemail. Here’s how the options compare and how to choose the right one for your business in 2026.',
    sections: [
      {
        heading: 'The two main types',
        bullets: [
          { title: 'Live virtual receptionists', body: 'Remote humans answer in your name, usually billed per minute or in monthly minute bundles. Personable, good for nuanced calls — but the cost scales with volume and coverage.' },
          { title: 'AI virtual receptionists', body: 'Software answers, books, and captures leads in a natural voice, 24/7, on a monthly plan with a set allowance of included minutes (plus a per-minute overage if you exceed it). Consistent and always available.' },
        ],
      },
      {
        heading: 'What to look for',
        bullets: [
          { title: 'Real calendar booking', body: 'It should read your live availability and book confirmed appointments — not just take messages.' },
          { title: '24/7 coverage', body: 'Nights and weekends are when many bookings happen. Make sure after-hours calls are actually answered.' },
          { title: 'Learns your business', body: 'It should answer your real FAQs — hours, services, pricing, location — from your own website and documents.' },
          { title: 'Clear reporting', body: 'You want a clean summary of every call, ideally synced to your CRM, Slack, or inbox.' },
          { title: 'Predictable pricing', body: 'Watch how minutes are billed. A plan with a clear included allowance and a stated overage rate is easier to budget than being metered from the first minute.' },
        ],
      },
      {
        heading: 'How to choose',
        paras: ['If you get a low volume of complex, high-touch calls, a live service may suit you. If you get a steady stream of bookings and enquiries — and you’re losing some to voicemail — an AI receptionist usually delivers better coverage for less, and never closes for the night. Many businesses start with an AI receptionist for the bulk of calls and keep escalation to a human for anything unusual.'],
      },
      {
        heading: 'Getting started with Open Lines',
        paras: ['Open Lines is an AI virtual receptionist built for local, appointment-driven businesses. It learns from your website, books into Google Calendar, Outlook, or Square Appointments, and reports every call to your inbox, Slack, or HubSpot. Setup takes under 10 minutes and there’s a 7-day free trial — nothing is charged until it ends.'],
      },
    ],
    faqs: [
      { q: 'What does a virtual receptionist do?', a: 'It answers your calls without being physically at your desk — booking appointments, answering common questions, and capturing leads. It can be a live remote person or an AI receptionist.' },
      { q: 'Is a virtual receptionist worth it for a small business?', a: 'If you’re losing calls to voicemail while you’re busy or closed, yes. Recovered bookings usually cover the cost quickly, especially with an AI plan that includes a block of minutes.' },
      { q: 'Live receptionist or AI — which is better?', a: 'AI wins on 24/7 coverage and pricing that’s easy to budget — a monthly plan with included minutes rather than a meter running from the first second; a live service can suit low volumes of complex calls. Many businesses use AI for most calls and escalate unusual ones to a human.' },
      { q: 'How quickly can I get set up?', a: 'With Open Lines, most businesses are live in under 10 minutes because it learns from your existing website.' },
    ],
    related: [
      { href: '/learn/answering-service-cost', label: 'What does an answering service cost?', sub: '2026 pricing, compared.' },
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How it answers and books.' },
      { href: '/pricing', label: 'See Open Lines pricing', sub: 'Monthly plans with included minutes.' },
    ],
    ctaHeading: 'Give your small business a receptionist that never clocks out.',
    ctaSub: 'Start a 7-day free trial and let it answer every call. Cancel anytime before you’re charged.',
  },
  {
    slug: 'automate-your-workflow-2026-ai',
    category: 'Guide',
    shortTitle: 'Automate your workflow with AI',
    metaTitle: 'Automate Your Workflow With AI: 2026 Guide | Open Lines',
    metaDescription: 'A practical 2026 guide to automating your workflow with AI — the tools worth using for calls, scheduling, CRM, payments and comms, plus tips to start small.',
    h1: 'How to automate your workflow in 2026 using AI',
    published: '2026-07-28',
    updated: '2026-07-30',
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
          { title: 'Open Lines', body: 'An AI receptionist that answers calls, books into Google Calendar, Outlook, or Square Appointments, captures leads, and reports each call to your inbox, Slack, or HubSpot. Monthly plans with included minutes, live in under 10 minutes.' },
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
    related: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'Automate the phone first.' },
      { href: '/learn/missed-call-text-back', label: 'Missed-call text-back', sub: 'Stop losing calls to voicemail.' },
      { href: '/integrations', label: 'Connect your tools', sub: 'Calendar, CRM, payments, and Slack.' },
    ],
    ctaHeading: 'Automate the one workflow that pays for itself first.',
    ctaSub: 'Put an AI receptionist on your phone in under 10 minutes. Start a 7-day free trial — cancel anytime before you’re charged.',
  },
  {
    slug: 'ai-call-routing',
    category: 'Feature guide',
    shortTitle: 'AI call routing',
    metaTitle: 'AI Call Routing & Warm Transfer, Explained | Open Lines',
    metaDescription: 'How AI call routing works: let AI answer the routine calls and warm-transfer the ones that need a person to the right teammate — with a safe callback if no one picks up.',
    h1: 'AI call routing and warm transfer, explained',
    published: '2026-08-09',
    updated: '2026-08-09',
    intro: 'An AI receptionist doesn’t have to replace your team — the best setup lets AI handle the routine calls and hand the rest to a human. That’s call routing: the AI answers every call, works out why someone’s calling, and transfers the ones who need a person to the right place, with a safe fallback if no one’s free. Here’s how it works and how to set it up in a few minutes.',
    sections: [
      {
        heading: 'What AI call routing actually does',
        paras: ['Instead of sending every caller to the same place — or to voicemail — call routing lets your AI receptionist triage the call and decide what should happen next.'],
        bullets: [
          { title: 'Answers and handles the routine', body: 'Hours, directions, pricing, and bookings are dealt with on the spot, so a person is only pulled in when they’re actually needed.' },
          { title: 'Works out the intent', body: 'The AI listens for why the caller is calling — a booking, a billing question, an urgent problem — before deciding where to send them.' },
          { title: 'Transfers the ones who need a person', body: 'Callers who need a human are connected to the right number — your front desk, an on-call line, or a specific team.' },
          { title: 'Falls back safely', body: 'If no one’s free, the AI takes a callback with the caller’s details instead of dropping them — nothing slips through.' },
        ],
      },
      {
        heading: 'Warm transfer vs. cold transfer',
        paras: ['Not all transfers are equal. The difference decides whether your teammate picks up prepared or caught off guard.'],
        bullets: [
          { title: 'Cold (blind) transfer', body: 'The call is pushed straight through with no context. Whoever answers starts from scratch — “Sorry, who’s this and what’s it about?”' },
          { title: 'Warm transfer', body: 'The AI dials your teammate first, gives a one-line summary of who’s calling and why, and only then connects the caller — so the handoff is smooth and the caller doesn’t repeat themselves.' },
          { title: 'Why it matters', body: 'Warm transfers feel like a real receptionist handing off a call. They cut confusion, speed up the handoff, and leave a better impression on the caller.' },
        ],
      },
      {
        heading: 'How the AI decides where a call goes',
        paras: ['Good routing is predictable, not a guess. A caller’s path is decided by a clear order of priority, so you always know where a given call will land.'],
        bullets: [
          { title: 'Urgent first', body: 'Time-sensitive callers are sent straight to your urgent or on-call line, ahead of everything else.' },
          { title: 'Rules by reason', body: 'Point specific reasons at specific destinations — “billing → accounts”, “new patient → front desk”.' },
          { title: 'A sensible default', body: 'Anyone else who needs a person goes to your default destination, so there’s never a dead end.' },
          { title: 'Always a safe fallback', body: 'If no destination fits or no one answers, the AI takes a callback — and it never dials emergency or premium-rate numbers.' },
        ],
      },
      {
        heading: 'No more missed calls during busy or after hours',
        paras: ['Because the AI answers every call on your line, the calls you used to miss — during a rush, at lunch, after closing, on weekends — get handled instead of going to voicemail. Routine questions are answered, and anyone who needs a person is either transferred (if someone’s available) or captured as a callback for later. Either way the caller gets a real response, and you get the lead.'],
      },
      {
        heading: 'Setting it up',
        paras: ['Call routing is available on the Pro and Business plans, and it’s opt-in — nothing changes on your calls until you switch it on.'],
        bullets: [
          { title: '1. Add your destinations', body: 'In Call Handling, add the phone numbers you want to transfer to. Domestic numbers only; they’re stored encrypted and shown masked.' },
          { title: '2. Choose where calls go', body: 'Set a default destination for anyone who needs a person, and an urgent / on-call destination for time-sensitive callers.' },
          { title: '3. Add rules (optional)', body: 'Send particular reasons to particular destinations if you want finer control.' },
          { title: '4. Turn it on and test', body: 'Flip the toggle, then use the built-in simulator to preview exactly how a caller would be routed — with no real call placed.' },
        ],
      },
      {
        heading: 'Where Open Lines fits',
        paras: ['Open Lines answers every call in a natural voice, handles the routine ones, and — on Pro and Business — warm-transfers the callers who need a person to the right teammate, with a safe callback if no one’s free. You set it up under Call Handling in a few minutes and preview it with the simulator before a single live call is affected. Compare plans on the pricing page and start a 7-day free trial — cancel anytime before you’re charged.'],
      },
    ],
    faqs: [
      { q: 'What’s the difference between a warm transfer and a cold transfer?', a: 'A cold (blind) transfer pushes the caller through with no context, so whoever answers starts from scratch. A warm transfer has the AI brief your teammate first — a one-line summary of who’s calling and why — and then connects the caller, so the handoff is smooth.' },
      { q: 'Can the AI transfer to different people based on why someone’s calling?', a: 'Yes. You set destinations and simple rules — for example “billing → accounts” or “urgent → on-call” — and the AI routes each caller to the right place, with a default for everyone else who needs a person.' },
      { q: 'What happens if no one answers the transfer?', a: 'The AI falls back safely: it takes a callback with the caller’s details instead of dropping them, so no lead is lost. It also never dials emergency or premium-rate numbers.' },
      { q: 'Does call routing work after hours?', a: 'Yes. The AI answers around the clock, handles routine calls, and either transfers to whoever’s available or captures a callback for later — so after-hours and weekend calls still get a real response.' },
      { q: 'Which plans include call routing?', a: 'AI call routing and warm transfer are available on the Pro and Business plans. Pro includes up to 2 destinations and 5 rules; Business up to 50 of each.' },
    ],
    related: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'How AI phone answering works.' },
      { href: '/learn/missed-call-text-back', label: 'Missed-call text-back', sub: 'Turn missed calls into booked jobs.' },
      { href: '/pricing', label: 'See Open Lines pricing', sub: 'Call routing is on Pro and Business.' },
    ],
    ctaHeading: 'Let AI handle the routine calls — and hand the rest to your team.',
    ctaSub: 'Set up call routing on Pro or Business in a few minutes. Start a 7-day free trial — cancel anytime before you’re charged.',
  },
  {
    slug: 'do-ai-receptionists-sound-human',
    category: 'Basics',
    shortTitle: 'Do AI receptionists sound human',
    metaTitle: 'Do AI Receptionists Sound Human? An Honest Answer — Open Lines',
    metaDescription: 'Most callers do not notice, some do, and it matters less than you think. What actually makes an AI receptionist sound natural, what still gives it away, and why disclosure is required anyway.',
    h1: 'Do AI receptionists sound human?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Mostly, yes — and the honest answer is that it varies by call. A short booking goes by without anyone noticing. A long, rambling or emotional call is where a caller starts to suspect. Here is what makes the difference, and why it matters less than the question implies.',
    sections: [
      {
        heading: 'What makes one sound natural',
        bullets: [
          { title: 'It waits properly', body: 'The biggest giveaway is not the voice, it is the turn-taking. An assistant that talks over someone, or leaves a beat of dead air after every sentence, reads as a machine no matter how good the voice is.' },
          { title: 'It knows your business', body: 'An assistant reading from a thin script hesitates on anything specific. One that has read your website answers "do you do balayage" without a pause, which is what a real receptionist sounds like.' },
          { title: 'It handles being interrupted', body: 'Real callers cut in. Stopping cleanly when they do is most of what people mean by "natural".' },
          { title: 'It does not oversell the voice', body: 'An unusually theatrical voice draws attention to itself. A slightly plain one does not.' },
        ],
      },
      {
        heading: 'What still gives it away',
        paras: ['Long digressions, strong accents it has not heard much of, heavy background noise, and callers who are upset. An AI receptionist handling a straightforward booking is genuinely hard to place. The same assistant faced with someone angry about an invoice is not — and that is the call you want routed to a person anyway.'],
      },
      {
        heading: 'Why it matters less than you think',
        paras: ['The comparison is not between an AI and your best receptionist on a good day. It is between an AI and the voicemail the call currently reaches at 7pm on a Saturday. Most callers do not leave voicemails. Whether they noticed the assistant was software is a smaller question than whether anyone picked up at all.'],
      },
      {
        heading: 'You have to tell them anyway',
        paras: ['In most places a caller must be told they are speaking to an automated system, and a recorded call needs disclosure too. So the goal is not to pass as human — it cannot be. The goal is to be clear, quick and useful enough that the caller does not mind.'],
      },
    ],
    faqs: [
      { q: 'Can callers tell it is AI?', a: 'Some can, particularly on longer or more difficult calls. On a straightforward booking most callers do not notice — but they are told, because disclosure is generally required.' },
      { q: 'Does a better voice make a difference?', a: 'Less than turn-taking does. An assistant that waits properly and stops when interrupted sounds more human than one with a better voice that talks over people.' },
      { q: 'Will callers hang up when they realise?', a: 'Some do, particularly older callers and people who wanted a specific person. Far fewer than hang up on a voicemail. Test it on your own line during a trial and judge it against what happens today, not against a perfect receptionist.' },
      { q: 'Can I change how it speaks?', a: 'Yes — the greeting, the name it uses, tone and pacing are all configurable, and you can hear it before any real caller does.' },
    ],
    related: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'The plain-English version.' },
      { href: '/learn/disclosing-ai-to-callers', label: 'Do you have to tell callers it is AI?', sub: 'What disclosure actually requires.' },
      { href: '/how-it-works', label: 'Hear what happens on a call', sub: 'Step by step.' },
    ],
    ctaHeading: 'Judge it on your own calls.',
    ctaSub: 'Seven days free. Ring it yourself before a customer does — cancel anytime before you are charged.',
  },
  {
    slug: 'disclosing-ai-to-callers',
    category: 'Compliance',
    shortTitle: 'Disclosing AI to callers',
    metaTitle: 'Do You Have to Tell Callers They Are Speaking to an AI? — Open Lines',
    metaDescription: 'What disclosure obligations apply when an AI answers your business phone, how they differ from call-recording consent, and what a compliant greeting sounds like.',
    h1: 'Do you have to tell callers they are speaking to an AI?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'In most places, yes — and it is a separate obligation from telling them the call is recorded. The two get confused constantly, and satisfying one does not satisfy the other. This is general information, not legal advice; check your own jurisdiction before you rely on it.',
    sections: [
      {
        heading: 'Two different obligations',
        bullets: [
          { title: 'Disclosing the AI', body: 'The caller should know they are talking to an automated system rather than a person. Several jurisdictions now require this explicitly for voice assistants, and the direction of travel everywhere else is the same.' },
          { title: 'Disclosing the recording', body: 'A separate question with its own rules, which vary far more by country and by US state. Being told "this is a virtual assistant" is not being told the call is recorded.' },
        ],
      },
      {
        heading: 'What a compliant greeting sounds like',
        paras: ['It is shorter than people expect. Naming the business, saying plainly that this is a virtual assistant, and noting that the call is recorded takes about five seconds and does not need a legal paragraph. The mistake is burying it — a disclosure the caller talks over is not a disclosure.'],
      },
      {
        heading: 'Why it is worth doing even where it is not required',
        paras: ['A caller who works it out halfway through feels misled, and that is a worse outcome than knowing at the start. Being told up front converts the question from "am I being tricked" into "can this thing book me in", which is the question you want them asking.'],
      },
    ],
    faqs: [
      { q: 'Is AI disclosure legally required?', a: 'In many jurisdictions yes, and the number is growing. Treat it as required unless you have advice saying otherwise for the places you operate.' },
      { q: 'Is that the same as telling them the call is recorded?', a: 'No. They are separate obligations with different rules, and one does not cover the other.' },
      { q: 'Does the disclosure have to be at the start?', a: 'It should be, and before anything is recorded or collected. A disclosure after the caller has already given their details is late.' },
      { q: 'Can I write my own wording?', a: 'Yes, and you should — it should sound like your business. Keep it short enough that nobody talks over it.' },
    ],
    sources: [
      { label: 'Office of the Privacy Commissioner of Canada — PIPEDA fair information principles', url: 'https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/' },
    ],
    related: [
      { href: '/learn/call-recording-consent', label: 'Is it legal to record business calls?', sub: 'Consent rules by country.' },
      { href: '/learn/do-ai-receptionists-sound-human', label: 'Do AI receptionists sound human?', sub: 'An honest answer.' },
      { href: '/privacy', label: 'How Open Lines handles call data', sub: 'Retention and deletion.' },
    ],
    ctaHeading: 'Disclosure handled, by default.',
    ctaSub: 'Open Lines discloses the assistant and the recording at the start of every call. Start a 7-day free trial.',
  },
  {
    slug: 'call-recording-consent',
    category: 'Compliance',
    shortTitle: 'Call recording consent',
    metaTitle: 'Is It Legal to Record Business Calls? Consent Rules by Country — Open Lines',
    metaDescription: 'One-party versus all-party consent, how Canada, the US, the UK, Ireland, Australia and New Zealand differ, and what that means when an AI answers your phone.',
    h1: 'Is it legal to record business calls?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Usually, with consent — but what counts as consent varies enormously, and the differences are the entire point. This is general information rather than legal advice, and it changes; confirm the rules for the places you actually operate before relying on any of it.',
    methodology: 'Written from the regulators’ own published guidance rather than secondary summaries, and deliberately kept general: consent rules change, and a page that states a specific rule with confidence is the page that becomes wrong first.',
    sections: [
      {
        heading: 'The distinction that matters',
        bullets: [
          { title: 'One-party consent', body: 'Only one participant needs to agree to the recording, and as the business on the call, that can be you. Common across Canada and in a majority of US states.' },
          { title: 'All-party consent', body: 'Everyone on the call must agree. Several US states work this way, which is why national businesses tend to announce recording on every call regardless of where the caller is.' },
          { title: 'Data-protection consent', body: 'A separate layer. In the EU, the UK and Ireland the recording is personal data, so lawful basis, retention and access rights all apply on top of whether you may record at all.' },
        ],
      },
      {
        heading: 'What this means in practice',
        paras: ['Most businesses do not try to work out which rule applies to each caller. They announce the recording at the start of every call, which satisfies the strictest rule they are likely to encounter and removes the need to guess where the caller is ringing from. It is the simplest defensible position and it costs a few seconds.'],
      },
      {
        heading: 'Recording is not the only obligation',
        paras: ['If you keep recordings or transcripts, you are holding personal data. That brings retention limits, deletion requests and a duty to keep it secure — and those apply whether or not the recording itself was lawful. Decide how long you keep call data before you start collecting it, not after someone asks you to delete theirs.'],
      },
      {
        heading: 'Where the AI changes things',
        paras: ['It adds a second disclosure rather than replacing the first. A caller should be told both that the call is recorded and that they are speaking to an automated system. They are different obligations and satisfying one does not satisfy the other.'],
      },
    ],
    faqs: [
      { q: 'Do I need consent to record a business call?', a: 'Almost always, in some form. Whether one party or all parties must consent depends on where you and the caller are, which is why most businesses announce the recording on every call.' },
      { q: 'Is one-party consent enough in Canada?', a: 'Canada generally operates on one-party consent for the recording itself, but PIPEDA still applies to the personal information in it — including why you collected it and how long you keep it.' },
      { q: 'What about the UK, Ireland and the EU?', a: 'The recording is personal data under GDPR, so you need a lawful basis, a retention period and a way to honour access and deletion requests — in addition to any rules on recording itself.' },
      { q: 'What if the caller objects?', a: 'Have an answer ready before it happens. Usually that means offering an alternative — a callback from a person, or an email address — rather than continuing to record someone who has said no.' },
      { q: 'How long should I keep recordings?', a: 'Only as long as you have a reason to. Pick a period, write it down, and delete on schedule. "Indefinitely" is not a retention policy and is hard to defend.' },
    ],
    sources: [
      { label: 'Office of the Privacy Commissioner of Canada — PIPEDA', url: 'https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/' },
      { label: 'UK Information Commissioner’s Office — Guide to UK GDPR', url: 'https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/' },
      { label: 'Data Protection Commission (Ireland)', url: 'https://www.dataprotection.ie/' },
    ],
    related: [
      { href: '/learn/disclosing-ai-to-callers', label: 'Do you have to tell callers it is AI?', sub: 'The other disclosure.' },
      { href: '/privacy', label: 'How Open Lines handles call data', sub: 'Retention and deletion.' },
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'The basics.' },
    ],
    ctaHeading: 'Recording and disclosure, handled on every call.',
    ctaSub: 'Open Lines announces both at the start, and you set how long call data is kept. Start a 7-day free trial.',
  },
  {
    slug: 'keep-your-business-phone-number',
    category: 'Basics',
    shortTitle: 'Keeping your number',
    metaTitle: 'Do I Need a New Phone Number for an AI Receptionist? — Open Lines',
    metaDescription: 'No. How call forwarding works, why you keep the number on your van and your Google listing, and when using the new number directly makes more sense.',
    h1: 'Do I need a new phone number?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'No. You get a dedicated number, and you choose whether to forward your existing line to it or hand the new one out. Most businesses forward, because the old number is printed on a van, a shopfront and a Google listing, and changing it costs more than it saves.',
    sections: [
      {
        heading: 'The two ways to run it',
        bullets: [
          { title: 'Forward your existing line', body: 'Callers keep dialling the number they already know. Your carrier forwards to the AI — either always, or only when you do not pick up within a few rings. Nothing printed anywhere has to change.' },
          { title: 'Use the new number directly', body: 'Simpler, and worth it if the new number is going somewhere fresh: a new location, a specific campaign, or a line you want measured separately.' },
        ],
      },
      {
        heading: 'Forward everything, or only what you miss',
        paras: ['Most carriers offer both. "Forward on no answer" lets your team pick up first and sends only the calls nobody reaches — which is usually the point. "Forward always" suits a business with no one on the phones at all. You can start with the first and move to the second once you trust it.'],
      },
      {
        heading: 'What about porting?',
        paras: ['Moving the number itself is a bigger step and rarely necessary. Forwarding gets you the same outcome in a few minutes, with none of the downtime risk. Port later if you decide you want the number to live with the service permanently.'],
      },
    ],
    faqs: [
      { q: 'Can I keep my existing business number?', a: 'Yes. Forward it to the number you are issued and callers carry on dialling what they already know.' },
      { q: 'Do I have to forward every call?', a: 'No. "Forward on no answer" sends only the calls your team does not reach, which is the setup most businesses choose.' },
      { q: 'Will callers see a different number?', a: 'On a forwarded call they dial yours. Your caller ID for outbound calls is unchanged, because the AI is inbound-only.' },
      { q: 'Do I need to port my number?', a: 'Not usually. Forwarding achieves the same thing in minutes without the downtime risk that porting carries.' },
      { q: 'What happens to the new number if I cancel?', a: 'It is released. If you forwarded your existing line, you simply turn the forwarding off and everything goes back to how it was.' },
    ],
    related: [
      { href: '/how-it-works', label: 'How setup works', sub: 'Live in under 10 minutes.' },
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'The basics.' },
      { href: '/pricing', label: 'See pricing', sub: 'From $99/month.' },
    ],
    ctaHeading: 'Keep your number. Stop missing calls on it.',
    ctaSub: 'Forward your line and let the AI answer what you cannot. Seven days free, cancel anytime.',
  },
  {
    slug: 'when-ai-does-not-know-the-answer',
    category: 'Basics',
    shortTitle: 'When it does not know',
    metaTitle: 'What Happens When the AI Receptionist Does Not Know? — Open Lines',
    metaDescription: 'A good AI receptionist does not guess. What it should do with a question it cannot answer, why that matters more than its hit rate, and how to widen what it knows.',
    h1: 'What happens if the AI does not know the answer?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'It should say so, take the question down, and pass it to you — not invent something. This is the single most important thing to test before you trust an assistant with real callers, and the easiest to check: ask it something obscure about your own business and listen to what it does.',
    sections: [
      {
        heading: 'What good behaviour looks like',
        bullets: [
          { title: 'It admits the gap', body: 'Plainly and without drama: it does not have that to hand.' },
          { title: 'It captures the question', body: 'The actual question, in the caller’s words, not a category. "Do you take my insurance" and "do you do payment plans" need different answers from you.' },
          { title: 'It commits to a follow-up', body: 'Says someone will come back to them, and takes a number to do it on.' },
          { title: 'It carries on', body: 'Not knowing one thing should not end the call. It can still take the booking.' },
        ],
      },
      {
        heading: 'Why this matters more than the hit rate',
        paras: ['An assistant that answers 95% of questions and invents the other 5% is worse than one that answers 80% and says so. A wrong answer about your prices, your hours or your policies reaches the caller as fact, and you only find out when they turn up expecting something you never offered. Guessing does not fail safely.'],
      },
      {
        heading: 'How to widen what it knows',
        paras: ['Most gaps are not model problems, they are knowledge problems. Your website does not say whether you take walk-ins, so the assistant cannot either. Read a week of call summaries, notice which questions keep coming back unanswered, and add those answers — a short document beats rewriting your website.'],
      },
      {
        heading: 'The questions it should never answer',
        paras: ['Some questions should go unanswered on purpose: anything that needs professional judgement, anything about someone else’s account, and anything where being wrong is expensive. The right response is to take a message, not to try harder.'],
      },
    ],
    faqs: [
      { q: 'Will it make something up?', a: 'It should not, and you should verify that before trusting it. Ask it something obscure about your business during the trial and listen to what it does with the gap.' },
      { q: 'How do I find out what it is missing?', a: 'Call summaries. The questions that keep arriving without good answers are the gaps, and they are usually the same handful.' },
      { q: 'Can I teach it something specific?', a: 'Yes. It learns from your website and from documents you upload, so a short FAQ document covers the things your site does not say.' },
      { q: 'Does it tell me when it could not answer?', a: 'It should appear in the summary for that call, along with the caller’s details, so the follow-up is possible.' },
    ],
    related: [
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'The basics.' },
      { href: '/learn/do-ai-receptionists-sound-human', label: 'Do AI receptionists sound human?', sub: 'An honest answer.' },
      { href: '/how-it-works', label: 'What it does on a call', sub: 'Step by step.' },
    ],
    ctaHeading: 'Test it on your hardest question.',
    ctaSub: 'Seven days free. Ask it something obscure and see what it does — cancel anytime before you are charged.',
  },
]

export const ARTICLE_SLUGS = ARTICLES.map(a => a.slug)

export function getArticle(slug: string): LearnArticle | undefined {
  return ARTICLES.find(a => a.slug === slug)
}
