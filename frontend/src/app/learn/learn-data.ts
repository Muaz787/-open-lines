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
        paras: ['Open Lines is an AI receptionist on a simple monthly plan: each plan includes a set number of minutes, with a per-minute overage rate only if you go over — and a call is never cut off mid-conversation. It answers every call in a natural voice, books appointments into your calendar, captures leads, and works 24/7. You can compare plans on the pricing page and start a 7-day free trial with no credit card.'],
      },
    ],
    faqs: [
      { q: 'Is an AI receptionist cheaper than a live answering service?', a: 'For most small businesses past a few calls a day, yes. Live services meter every minute from the start, so cost rises with call volume, while an AI plan gives you a block of included minutes for a monthly fee — with overage only beyond it — and covers nights and weekends.' },
      { q: 'Does Open Lines charge per minute?', a: 'Each Open Lines plan includes a set number of minutes for a flat monthly price. If you go over your included minutes, the extra time is billed at your plan’s per-minute overage rate — and calls are never cut off mid-conversation. See the pricing page for current plans and rates.' },
      { q: 'What does a full-time receptionist cost?', a: 'In Canada, receptionist wages typically run about $40,000–$62,000 per year (roughly $18–$20+ per hour) before benefits and overhead — and that only covers working hours, not after-hours or weekend calls.' },
      { q: 'Can I try it before paying?', a: 'Yes. Open Lines offers a 7-day free trial with no credit card, so you can see how it handles your calls before committing.' },
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
    ctaSub: 'Start a 7-day free trial — no credit card — and let it answer your next call.',
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
        paras: ['Open Lines is an AI virtual receptionist built for local, appointment-driven businesses. It learns from your website, books into Google Calendar, Outlook, or Square Appointments, and reports every call to your inbox, Slack, or HubSpot. Setup takes under 10 minutes and there’s a 7-day free trial with no credit card.'],
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
    ctaSub: 'Start a 7-day free trial — no credit card — and let it answer every call.',
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
    ctaSub: 'Put an AI receptionist on your phone in under 10 minutes. Start a 7-day free trial — no credit card.',
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
        paras: ['Open Lines answers every call in a natural voice, handles the routine ones, and — on Pro and Business — warm-transfers the callers who need a person to the right teammate, with a safe callback if no one’s free. You set it up under Call Handling in a few minutes and preview it with the simulator before a single live call is affected. Compare plans on the pricing page and start a 7-day free trial with no credit card.'],
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
    ctaSub: 'Set up call routing on Pro or Business in a few minutes. Start a 7-day free trial — no credit card.',
  },
]

export const ARTICLE_SLUGS = ARTICLES.map(a => a.slug)

export function getArticle(slug: string): LearnArticle | undefined {
  return ARTICLES.find(a => a.slug === slug)
}
