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
  {
    slug: 'ai-receptionist-book-appointments',
    category: 'Feature guide',
    shortTitle: 'How AI booking works',
    metaTitle: 'Can an AI Receptionist Actually Book Appointments? — Open Lines',
    metaDescription: 'How an AI receptionist reads live calendar availability, avoids double-bookings, books a named staff member, and handles cancellations — plus where it should stop.',
    h1: 'Can an AI receptionist actually book appointments?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Yes — but "books appointments" covers two very different things, and the difference decides whether it saves you work or makes more. One reads your real calendar and writes a confirmed booking into it. The other takes a preferred time and leaves someone to sort it out later. Only the first is worth having.',
    sections: [
      {
        heading: 'The distinction that matters',
        bullets: [
          { title: 'Real booking', body: 'The assistant reads your live availability before it offers a time, so the slots it names are genuinely free. When the caller says yes, the appointment is written into the same calendar your walk-ins and online bookings live in.' },
          { title: 'A request, dressed up as a booking', body: 'The assistant takes a preferred time and emails it to you. The caller believes they are booked. You still have to check and confirm — and if the slot has gone, you have to ring them back and take it away.' },
        ],
      },
      {
        heading: 'Why double-booking is the real test',
        paras: ['Any assistant can read out times. The question is what it does with a slot that was taken two minutes ago by someone walking in. If it is reading your live calendar, that slot is simply not offered — bookings made anywhere else are already reflected, because it is looking at the same calendar. If it is working from a copy, or from opening hours, it will eventually book two people into one chair.'],
      },
      {
        heading: 'What a good one gets right beyond the slot',
        bullets: [
          { title: 'The right service', body: 'A cut and a colour are not the same length. Booking the wrong service produces a clash later even when the slot was free.' },
          { title: 'The right person', body: 'If the caller asks for someone by name, it should check that person’s availability — not the business’s.' },
          { title: 'The right place', body: 'For a business with several branches, availability has to be scoped to the branch the caller wants, or you will book someone into the wrong town.' },
          { title: 'Cancelling and moving', body: 'Half of appointment calls are not new bookings. An assistant that cannot cancel or reschedule sends those to voicemail.' },
        ],
      },
      {
        heading: 'Where it should stop',
        paras: ['Some bookings need judgement — a first consultation that might not be appropriate, a job that needs quoting before it is scheduled, a customer with an outstanding balance. A good assistant recognises those, takes the details and hands them over, rather than booking something you then have to unpick.'],
      },
    ],
    faqs: [
      { q: 'Which calendars can it book into?', a: 'Open Lines books into Google Calendar, Microsoft Outlook and Square Appointments, reading live availability from each before it offers a caller a time.' },
      { q: 'Can it double-book?', a: 'Not if it is reading your live calendar, which it is. Bookings made online, in person or by a colleague are already visible to it, because it is the same calendar.' },
      { q: 'Can a caller ask for a specific person?', a: 'Yes, where your calendar has per-staff availability. On Square Appointments your team members come across when you connect, so it checks that person’s real availability.' },
      { q: 'Can it cancel or move an appointment?', a: 'Yes, on Square Appointments. It can cancel, and it can move an appointment to a new time for the same service at the same location.' },
      { q: 'Does the customer get a confirmation?', a: 'Yes, and so do you — a summary of the call with the booking details, by email and optionally by text or WhatsApp.' },
    ],
    related: [
      { href: '/integrations/square-appointments', label: 'Booking into Square Appointments', sub: 'Services, staff and branches.' },
      { href: '/multi-location', label: 'Several branches?', sub: 'One line, the right location.' },
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'The basics.' },
    ],
    ctaHeading: 'Let it book into the calendar you already use.',
    ctaSub: 'Google, Outlook or Square — connected in a couple of clicks. Seven days free, cancel anytime.',
  },
  {
    slug: 'will-customers-mind-an-ai-receptionist',
    category: 'Basics',
    shortTitle: 'Will customers mind',
    metaTitle: 'Will My Customers Mind Talking to an AI Receptionist? — Open Lines',
    metaDescription: 'The objection every owner has. Who actually minds, what makes it worse, what makes it fine, and the comparison that matters — an AI against your voicemail, not against your best receptionist.',
    h1: 'Will my customers mind talking to an AI?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Some will. Fewer than you fear, more than any vendor will admit, and almost entirely depending on what the alternative was. This is the objection that stops most owners, and it deserves a straighter answer than it usually gets.',
    sections: [
      {
        heading: 'Who actually minds',
        bullets: [
          { title: 'People who wanted a specific person', body: 'Regulars ringing to speak to someone they know. They are not objecting to AI, they are objecting to not getting who they asked for — which is a routing problem, not a technology one.' },
          { title: 'People with a complicated problem', body: 'Anyone with a complaint or an unusual situation wants a human with discretion. They are right to.' },
          { title: 'People who have had a bad one', body: 'Anybody burned by a phone menu that would not let them out. That is a reasonable prior and you inherit it.' },
        ],
      },
      {
        heading: 'What makes it worse',
        paras: ['Pretending. An assistant that dodges the question of whether it is a person turns a neutral call into an adversarial one the moment the caller works it out — and they usually do. Trapping people is the other one: if there is no way to reach a human and no promise of a callback, a caller who needs one is stuck, and that is the experience they will describe to other people.'],
      },
      {
        heading: 'What makes it fine',
        paras: ['Being useful quickly. A caller who wanted a Tuesday appointment and got a Tuesday appointment in ninety seconds does not spend the afternoon thinking about what answered. The complaint is almost never "that was AI" — it is "that wasted my time", and the same complaint applies to a person who put them on hold for six minutes.'],
      },
      {
        heading: 'The comparison that actually matters',
        paras: ['Not AI versus your best receptionist. AI versus what happens today at 7pm on a Saturday, which is voicemail — and most callers do not leave one. The question is not whether some callers would prefer a person. It is whether more of them get what they rang for than currently do.'],
      },
      {
        heading: 'How to find out for your own callers',
        paras: ['Do not take anybody’s word for it, including ours. Run it on after-hours calls first, where the alternative is provably nothing, and read the summaries. You will see within a week how many people engaged, how many hung up, and how many booked. That is your answer, and it is specific to your business in a way no industry statistic is.'],
      },
    ],
    faqs: [
      { q: 'Do callers hang up on AI receptionists?', a: 'Some do. Far fewer than hang up on voicemail without leaving a message. Measure it on your own line during a trial rather than relying on anyone’s averages.' },
      { q: 'Should I tell callers it is an AI?', a: 'Yes, and in most places you must. It also works better: a caller told at the start asks "can this book me in", instead of feeling misled halfway through.' },
      { q: 'What about my regular customers?', a: 'Start with after-hours and overflow, where the alternative is voicemail. Your regulars ringing during opening hours still reach your team.' },
      { q: 'Can a caller always reach a person?', a: 'They should always be able to get a callback promise and leave their number. An assistant with no escape route is the thing people actually object to.' },
    ],
    related: [
      { href: '/learn/do-ai-receptionists-sound-human', label: 'Do AI receptionists sound human?', sub: 'An honest answer.' },
      { href: '/learn/when-ai-does-not-know-the-answer', label: 'What if it does not know?', sub: 'Why guessing is worse.' },
      { href: '/compare', label: 'Compare the alternatives', sub: 'Including doing nothing.' },
    ],
    ctaHeading: 'Try it where the alternative is voicemail.',
    ctaSub: 'Run it on after-hours calls for a week and read the summaries. Seven days free, cancel anytime.',
  },
  {
    slug: 'ai-receptionist-after-hours',
    category: 'Guide',
    shortTitle: 'After-hours answering',
    metaTitle: 'After-Hours Call Answering for Small Business — Open Lines',
    metaDescription: 'Why evenings and weekends are where an AI receptionist earns its keep, what callers do when nobody answers, and how to start with after-hours only.',
    h1: 'Does an AI receptionist work after hours?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'It does, and that is where most of the value is. Not because evenings are busy, but because the alternative at 8pm is nothing at all — and a call that reaches nothing is the only kind you are guaranteed to lose.',
    sections: [
      {
        heading: 'What happens now, at 8pm',
        paras: ['The call rings out or reaches voicemail. Most people do not leave one — they ring the next business on the list, and whoever answers gets the job. You never learn the call happened, which is what makes after-hours losses so easy to underestimate: there is no record of them anywhere.'],
      },
      {
        heading: 'Why after-hours is the right place to start',
        bullets: [
          { title: 'The comparison is honest', body: 'You are not weighing AI against your receptionist. You are weighing it against silence, which makes the result easy to read.' },
          { title: 'The stakes are low', body: 'Nothing that currently works can break, because nothing currently happens.' },
          { title: 'Your regulars are unaffected', body: 'Daytime calls still reach your team. Only the calls nobody was going to answer change.' },
          { title: 'The numbers show up quickly', body: 'A week of summaries tells you how many evening calls you have been missing — usually more than expected.' },
        ],
      },
      {
        heading: 'How to set it up this way',
        paras: ['Use "forward on no answer" rather than forwarding everything. Your team picks up first during the day; anything nobody reaches goes to the assistant, whatever the hour. That covers evenings and weekends and also lunchtime, sickness and the days you are simply too busy — without you having to manage a schedule.'],
      },
      {
        heading: 'What it can do at 2am',
        paras: ['Everything it does at 2pm: answer questions from your own website and documents, book a genuinely free slot in your calendar, take a deposit where you have that switched on, and send you a summary before you wake up. The appointment is in your calendar when you open it, and you did nothing.'],
      },
    ],
    faqs: [
      { q: 'Does it work at weekends and on holidays?', a: 'Yes. There is no schedule to manage — it answers whenever a call reaches it, including nights, weekends and holidays.' },
      { q: 'Can I use it only after hours?', a: 'Yes, and it is the best way to start. Set your line to forward on no answer, so your team takes daytime calls and the assistant takes what nobody reaches.' },
      { q: 'Will it book appointments overnight?', a: 'Yes, into real availability. The booking is in your calendar when you open it, and the caller already has their confirmation.' },
      { q: 'What about genuine emergencies at night?', a: 'It is not an emergency service and must never be used as one. What it can do is recognise urgency, take the details and flag the call so you see it first.' },
    ],
    related: [
      { href: '/learn/missed-call-text-back', label: 'Missed-call text-back', sub: 'Turn missed calls into jobs.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Do I need a new number?', sub: 'No — forward your line.' },
      { href: '/compare', label: 'Compare the alternatives', sub: 'Including voicemail.' },
    ],
    ctaHeading: 'Start with the calls you are already losing.',
    ctaSub: 'Forward on no answer and let it take the evenings. Seven days free, cancel anytime.',
  },
  {
    slug: 'is-an-ai-receptionist-worth-it',
    category: 'Cost guide',
    shortTitle: 'Is it worth it',
    metaTitle: 'Is an AI Receptionist Worth It for a Small Business? — Open Lines',
    metaDescription: 'The arithmetic that decides it, the businesses it does not suit, and how to test the answer for yourself in a week rather than arguing about averages.',
    h1: 'Is an AI receptionist worth it for a small business?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'It depends on one number: what a booked customer is worth to you. For a salon at £45 a head the maths is different from a roofer at £4,500 a job, and it is different again for a business whose callers reliably leave voicemails. Here is how to work out your own answer instead of accepting an average.',
    methodology: 'The worked examples below use round numbers and state every assumption, because an ROI figure whose assumptions are hidden is not a calculation — it is a claim. Substitute your own figures; the method is the point, not the numbers.',
    sections: [
      {
        heading: 'The arithmetic',
        paras: ['Take the number of calls you miss in a month — your phone records have this, and it is usually higher than the guess. Assume some fraction of those would have become customers had anyone answered; a quarter is a conservative starting point for appointment businesses. Multiply by what a customer is worth on their first visit. Compare that with the monthly cost. Most of the time the answer is obvious in one direction or the other, which is why the calculation is worth five minutes.'],
      },
      {
        heading: 'Two worked examples',
        bullets: [
          { title: 'A salon missing 40 calls a month', body: 'At a 25% conversion and £45 a visit, that is ten customers and £450 of first visits — before anyone rebooks. Against a subscription in the low hundreds, it pays back on the recovered bookings alone.' },
          { title: 'A roofer missing 15 calls a month', body: 'At a 10% conversion and £4,500 a job, that is one and a half jobs. The subscription is a rounding error against a single recovered job, and the real question is whether the calls are being missed at all.' },
        ],
      },
      {
        heading: 'When it is not worth it',
        bullets: [
          { title: 'Your callers leave voicemails and you ring them back', body: 'If that genuinely happens same-day, you are not losing the calls and the main benefit does not apply.' },
          { title: 'Your calls need judgement from the first sentence', body: 'If almost every call needs a person to decide something, an assistant handles the minority and you are paying for the wrong tool.' },
          { title: 'You do not take appointments', body: 'Most of the value is in booking. Without that, you are buying a message-taker, and cheaper ones exist.' },
          { title: 'Your volume is genuinely tiny', body: 'Two or three calls a week, all answered, is not a problem worth a subscription.' },
        ],
      },
      {
        heading: 'Test it rather than argue about it',
        paras: ['Every number above is someone else’s. Run it for a week on the calls you currently miss, read the summaries, and count what it booked. That converts the question from a debate about AI into a figure from your own business — and if the figure is small, you have learned something useful for the price of a week.'],
      },
    ],
    faqs: [
      { q: 'How much does an AI receptionist cost?', a: 'Open Lines starts at $99/month with no setup fee and no contract. The variable that decides whether it pays is not the price, it is what a booked customer is worth to you.' },
      { q: 'How many missed calls do I need for it to pay for itself?', a: 'Divide the monthly cost by the value of one first visit, then by your conversion rate. For most appointment businesses the answer is a handful of recovered bookings a month.' },
      { q: 'How do I know how many calls I am missing?', a: 'Your phone provider’s call records show unanswered calls. It is almost always higher than the estimate, because missed evening calls leave no trace anywhere else.' },
      { q: 'Is it cheaper than hiring someone?', a: 'Considerably, but they are not the same thing. A person handles judgement and complaints; an assistant handles volume and hours. Businesses that need both usually keep both.' },
      { q: 'What if it does not work for me?', a: 'You will know in a week, from your own summaries rather than a projection. That is the point of running the trial on real calls.' },
    ],
    related: [
      { href: '/learn/answering-service-cost', label: 'What does an answering service cost?', sub: 'Pricing models compared.' },
      { href: '/compare', label: 'Compare the alternatives', sub: 'And when to pick one.' },
      { href: '/pricing', label: 'See pricing', sub: 'From $99/month.' },
    ],
    ctaHeading: 'Get your own number, not ours.',
    ctaSub: 'Run it for a week on the calls you are missing and count what it books. Cancel anytime before you are charged.',
  },
  {
    slug: 'reduce-no-shows-with-deposits',
    category: 'Feature guide',
    shortTitle: 'Deposits and no-shows',
    metaTitle: 'How to Reduce No-Shows With a Deposit at Booking — Open Lines',
    metaDescription: 'Why a deposit taken during the call works when reminders do not, what it costs you in refused bookings, and how to pick an amount that does not scare people off.',
    h1: 'How to reduce no-shows with a deposit',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'A no-show is worse than a cancellation: the slot is gone and nobody paid for it. Reminders help at the margins, but the thing that changes behaviour is having something at stake — which is why a deposit taken during the booking call works where a text the night before does not.',
    sections: [
      {
        heading: 'Why deposits work when reminders do not',
        paras: ['A reminder assumes the customer forgot. Most no-shows have not forgotten — something else came up and the appointment had no cost attached, so it lost. A deposit changes that calculation before they ever need to weigh it up, which is why the moment it is taken matters more than the amount.'],
      },
      {
        heading: 'Why during the call is the moment',
        bullets: [
          { title: 'They have already decided', body: 'Someone who has just agreed a time is at their most committed. A payment link the next day arrives after that moment has passed.' },
          { title: 'Nobody has to chase', body: 'A deposit requested later is a task for somebody. A deposit requested on the call is part of the booking.' },
          { title: 'It filters gently', body: 'A caller unwilling to put down a small amount was, quite often, the no-show. Finding out during the call is cheaper than finding out on the day.' },
        ],
      },
      {
        heading: 'Picking an amount',
        paras: ['Large enough to matter, small enough not to end the call. For most appointment businesses that is a fraction of the service price rather than the whole thing — enough that skipping it feels like a loss, not so much that it reads as distrust. Whether it is refundable, and by when, matters as much as the number: a clear cancellation window makes a deposit feel fair rather than punitive.'],
      },
      {
        heading: 'What it costs you',
        paras: ['Some bookings, honestly. A proportion of callers will decline and hang up, and a few of those would have turned up. The trade is a smaller number of more reliable bookings against a larger number of less reliable ones — which is worth it when your constraint is chair time rather than demand, and is not when you are trying to fill an empty diary.'],
      },
      {
        heading: 'Where it fits with everything else',
        paras: ['A deposit is not a substitute for a reminder, it is the layer underneath. Take the deposit at booking, send the reminder anyway, and make cancelling easy — a customer who cancels on Tuesday gives you a slot you can resell, which is the outcome you actually want from someone who is not coming.'],
      },
    ],
    faqs: [
      { q: 'Can an AI receptionist take a deposit on the call?', a: 'Yes. On Pro and Business plans Open Lines can text a secure payment link during the call, so the deposit is taken at the moment the caller commits.' },
      { q: 'Does it take the card details over the phone?', a: 'No. A payment link is sent by text and the customer pays through Stripe or Square. Card details are never spoken aloud or recorded.' },
      { q: 'How much should the deposit be?', a: 'Enough to matter and not enough to end the call — usually a fraction of the service price. Pair it with a clear cancellation window so it reads as fair.' },
      { q: 'Will I lose bookings because of it?', a: 'Some, yes. The trade is fewer, more reliable bookings. That is a good trade when your constraint is available time, and a bad one when you are trying to fill an empty diary.' },
      { q: 'Can I take deposits for some services and not others?', a: 'Yes. It is common to require one for long or high-value appointments and skip it for short ones.' },
    ],
    related: [
      { href: '/integrations/stripe', label: 'Deposits with Stripe', sub: 'Collected at booking.' },
      { href: '/integrations/square-appointments', label: 'Booking into Square', sub: 'With a deposit alongside.' },
      { href: '/learn/ai-receptionist-book-appointments', label: 'How AI booking works', sub: 'Live availability, real bookings.' },
    ],
    ctaHeading: 'Take the deposit while they are still on the phone.',
    ctaSub: 'Available on Pro and Business. Seven days free, cancel anytime before you are charged.',
  },
  {
    slug: 'how-an-ai-receptionist-learns-your-business',
    category: 'Feature guide',
    shortTitle: 'How it learns',
    metaTitle: 'How Does an AI Receptionist Learn About My Business? — Open Lines',
    metaDescription: 'Where the answers come from, why a website beats a script, what to upload when your site is thin, and how to find the gaps from your own call summaries.',
    h1: 'How does an AI receptionist learn about my business?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'From whatever you give it — and the difference between a useful assistant and a frustrating one is almost entirely here, not in the voice. An assistant that knows your cancellation policy sounds competent. One that does not sounds like a phone menu with better manners.',
    sections: [
      {
        heading: 'Three places the answers come from',
        bullets: [
          { title: 'Your website', body: 'The fastest start, because it already exists. Services, hours, locations and pricing get read and turned into something the assistant can answer from — no forms to fill in.' },
          { title: 'Documents you upload', body: 'For everything your website does not say out loud: price lists, policies, aftercare instructions, the answers your team gives twenty times a week. A scanned menu or PDF works as well as a typed one.' },
          { title: 'What you tell it directly', body: 'The greeting, the name it answers as, your opening hours and the specific things you want it always to say — or never to.' },
        ],
      },
      {
        heading: 'Why a website beats a script',
        paras: ['A scripted assistant knows exactly what somebody thought to write down, which is never enough. Real callers ask about parking, whether you take walk-ins, if you do gift vouchers. Learning from your site means the assistant starts with everything you have already published, and the gaps that remain are real gaps rather than transcription failures.'],
      },
      {
        heading: 'What to add when your website is thin',
        paras: ['Most sites are marketing, not reference. They say "expert colour services" and not "a full head of highlights takes three hours and costs from £120". If your assistant keeps missing questions, the answer is usually a one-page document written the way you would actually answer on the phone — not a website rewrite.'],
      },
      {
        heading: 'Finding the gaps without guessing',
        paras: ['Read a week of call summaries. The questions that keep coming back unanswered are your list, and it is usually shorter than expected — five or six things covering most of what the assistant could not handle. Add those, and the difference in the following week is obvious.'],
      },
      {
        heading: 'Keeping it current',
        paras: ['Prices change and pages get edited. A re-crawl on a schedule keeps the assistant aligned with your site without anyone remembering to do it, which matters most for the things that change quietly — hours over a holiday, a service you stopped offering.'],
      },
    ],
    faqs: [
      { q: 'Do I have to write a script?', a: 'No. Open Lines reads your website and builds the knowledge from that, then you add documents for anything your site does not cover.' },
      { q: 'What file types can I upload?', a: 'Common documents and PDFs, including scanned ones — a photographed price list is read the same way a typed one is.' },
      { q: 'How do I know what it does not know?', a: 'Your call summaries. Questions it could not answer appear there with the caller’s details, and the same handful usually accounts for most of them.' },
      { q: 'What if I change my prices?', a: 'Update your site or your uploaded document. Scheduled re-crawling keeps the assistant aligned with your website without you having to remember.' },
      { q: 'Can I stop it answering certain things?', a: 'Yes, and you should for anything needing professional judgement. Those become a message and a callback rather than an answer.' },
    ],
    related: [
      { href: '/learn/when-ai-does-not-know-the-answer', label: 'What if it does not know?', sub: 'Why guessing is worse.' },
      { href: '/learn/what-is-an-ai-receptionist', label: 'What is an AI receptionist?', sub: 'The basics.' },
      { href: '/how-it-works', label: 'How setup works', sub: 'Live in under 10 minutes.' },
    ],
    ctaHeading: 'Point it at your website and listen.',
    ctaSub: 'It learns your business before you configure anything. Seven days free, cancel anytime.',
  },
  {
    slug: 'ai-receptionist-call-data-privacy',
    category: 'Compliance',
    shortTitle: 'Call data and privacy',
    metaTitle: 'What Happens to My Call Data? AI Receptionist Privacy — Open Lines',
    metaDescription: 'What gets stored when an AI answers your phone, who it belongs to, how long it is kept, and the questions to ask any vendor before you hand them your callers.',
    h1: 'What happens to my call data?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'When an AI answers your phone, your callers’ names, numbers and reasons for calling end up in somebody else’s system. That makes you responsible for something you no longer physically hold — so it is worth knowing what is kept, for how long, and what you can do about it. General information, not legal advice.',
    sections: [
      {
        heading: 'What actually gets stored',
        bullets: [
          { title: 'The transcript', body: 'What was said, on both sides. This is the most sensitive artefact, because callers volunteer things nobody asked for.' },
          { title: 'Caller details', body: 'Name, phone number, and whatever the call was about — which is personal data the moment it identifies someone.' },
          { title: 'The booking', body: 'What was booked, when, and with whom. This usually also lives in your own calendar.' },
          { title: 'The summary', body: 'A short account of the call, which is the bit you actually read.' },
        ],
      },
      {
        heading: 'It is your data, and your responsibility',
        paras: ['In most jurisdictions you are the one who decides why this information is collected, which makes you accountable for it even though a vendor is holding it. That is not a technicality — it means a deletion request from one of your callers is yours to honour, and you need a vendor who can actually carry it out rather than one who has never been asked.'],
      },
      {
        heading: 'The questions worth asking any vendor',
        bullets: [
          { title: 'How long do you keep transcripts?', body: '"As long as necessary" is not an answer. A number is.' },
          { title: 'Can you delete one caller?', body: 'Not one account — one person, on request, because that is what the law contemplates.' },
          { title: 'What happens when I cancel?', body: 'Ask what is deleted, when, and whether you can export first.' },
          { title: 'Who else can see it?', body: 'Which sub-processors are involved, and where they operate.' },
          { title: 'Do you record audio?', body: 'Audio and text carry different risks. Some services keep both; not all need to.' },
        ],
      },
      {
        heading: 'Decide retention before you collect anything',
        paras: ['The easiest mistake is keeping everything forever because nobody chose otherwise. Pick a period that matches why you need the data — long enough to handle a dispute, short enough that a breach is bounded — write it down, and make sure it happens automatically. A policy nobody enforces is worse than none, because it is a promise you are not keeping.'],
      },
    ],
    faqs: [
      { q: 'Who owns the call data?', a: 'You do, in the sense that matters: you decide why it is collected, and you are accountable for it. The vendor processes it on your behalf.' },
      { q: 'How long should call recordings be kept?', a: 'Only as long as you have a reason. Choose a period, document it, and enforce it automatically — "indefinitely" is difficult to defend to a regulator or a customer.' },
      { q: 'Can a caller ask for their data to be deleted?', a: 'In most jurisdictions yes, and you have to be able to do it. Check your vendor can delete one individual rather than only a whole account.' },
      { q: 'Does Open Lines record audio?', a: 'Open Lines is transcript-based rather than audio-archiving. Transcripts and summaries are retained according to the retention settings on your account.' },
      { q: 'What happens to my data if I cancel?', a: 'Ask before you sign up, not after. Look for a stated deletion timeline and a way to export anything you need to keep.' },
    ],
    sources: [
      { label: 'Office of the Privacy Commissioner of Canada — PIPEDA', url: 'https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/' },
      { label: 'UK Information Commissioner’s Office — Guide to UK GDPR', url: 'https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/' },
    ],
    related: [
      { href: '/learn/call-recording-consent', label: 'Is it legal to record calls?', sub: 'Consent rules by country.' },
      { href: '/learn/disclosing-ai-to-callers', label: 'Telling callers it is AI', sub: 'A separate obligation.' },
      { href: '/privacy', label: 'Open Lines privacy policy', sub: 'What we keep, and for how long.' },
    ],
    ctaHeading: 'Ask us the questions on this page.',
    ctaSub: 'We would rather you asked before signing up than after. Start a 7-day free trial.',
  },
  {
    slug: 'irish-business-phone-number',
    category: 'Guide',
    shortTitle: 'Irish business numbers',
    metaTitle: 'Getting an Irish Business Phone Number: What Verification Requires — Open Lines',
    metaDescription: 'Why Irish numbers need business verification, exactly what documentation is asked for, how long you wait, and what happens to your phone line in the meantime.',
    h1: 'Getting an Irish business phone number',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Irish numbers are regulated, which surprises most people setting up a business line for the first time. You cannot simply buy one — the regulator requires the registered details of the business it belongs to, a named person responsible for it, and a verified Irish address. Here is what that actually involves.',
    sections: [
      {
        heading: 'Why Ireland is different',
        paras: ['Some countries issue phone numbers freely; Ireland does not. Numbers are tied to a verified business identity, which is a consumer-protection measure — it means a number can be traced to a real, registered entity. The practical consequence is a short verification step before a number is issued, not after.'],
      },
      {
        heading: 'What you are asked for',
        bullets: [
          { title: 'Your registered business name', body: 'Exactly as it appears on the Companies Registration Office register. Trading names and abbreviations cause rejections.' },
          { title: 'A registration number', body: 'Your CRO number, a Registered Charity Number, or your full organisation name if you are a public-sector body.' },
          { title: 'An authorised representative', body: 'A named person senior enough to be responsible for the numbers, with an email address that regulatory correspondence can reach.' },
          { title: 'A verified Irish address', body: 'The premises the number is registered to, including Eircode. It has to be a real address in Ireland, not a forwarding service.' },
        ],
      },
      {
        heading: 'What the wait looks like',
        paras: ['The details go to the telecoms provider, who files them with the regulator. Review takes as long as it takes — it is not a queue anyone can jump, and no vendor can promise you a date. What a vendor can tell you is exactly where your filing is, and what to do if corrections are requested.'],
      },
      {
        heading: 'What to do while you wait',
        paras: ['Not nothing. A temporary number from an unregulated country lets you test the whole system end to end — answering, booking, summaries — before your real line is live. It is not your business number and should never be published as one, but it means verification is not dead time, and you find any problems before real customers are involved.'],
      },
      {
        heading: 'Where it goes wrong',
        bullets: [
          { title: 'A name that does not match', body: 'The most common rejection. Copy it from the CRO register rather than from your letterhead.' },
          { title: 'An address that is not verifiable', body: 'It has to be a genuine premises with a valid Eircode.' },
          { title: 'A representative who is not authorised', body: 'The named person must actually be able to take responsibility for the numbers.' },
        ],
      },
    ],
    faqs: [
      { q: 'Why does an Irish number need business verification?', a: 'Irish numbering is regulated, and numbers must be traceable to a verified business. It is a requirement on the telecoms provider, not a vendor’s choice.' },
      { q: 'What documents do I need?', a: 'Your registered business name as it appears on the CRO register, a CRO or charity registration number, a named authorised representative with a contact email, and a verifiable Irish address including Eircode.' },
      { q: 'How long does verification take?', a: 'It depends on the regulator and cannot be promised by any vendor. Treat anyone offering a guaranteed date with suspicion.' },
      { q: 'Can I use the service while I wait?', a: 'With Open Lines, yes — a temporary test number lets you try the whole system while the filing is reviewed. It is clearly marked as not your business number.' },
      { q: 'Does my trial start during verification?', a: 'With Open Lines it does not. The trial begins when your permanent Irish number is approved and live, so you are not spending trial days waiting on a regulator.' },
      { q: 'What if my filing is rejected?', a: 'Usually a detail does not match — most often the business name. The filing is corrected and resubmitted rather than started again.' },
    ],
    related: [
      { href: '/integrations/square-appointments', label: 'Booking into Square', sub: 'Popular with Irish retail.' },
      { href: '/multi-location', label: 'Several branches?', sub: 'One line, the right location.' },
      { href: '/pricing', label: 'See pricing', sub: 'From $99/month.' },
    ],
    ctaHeading: 'Start the verification, test while you wait.',
    ctaSub: 'A temporary number lets you try everything before your Irish line is live. Seven days free once it is.',
  },
  {
    slug: 'customising-your-ai-receptionist',
    category: 'Feature guide',
    shortTitle: 'Making it sound like you',
    metaTitle: 'Can I Change What the AI Receptionist Says? — Open Lines',
    metaDescription: 'What you can actually change — the name it answers as, the greeting, the voice, your hours, and what it must never say — and which of those matter most.',
    h1: 'Can I change what the AI says?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Yes, and more of it matters than people expect. Most owners go straight to the voice, which is the setting that changes the least. The greeting and the boundaries are what callers actually notice.',
    sections: [
      {
        heading: 'What you can change',
        bullets: [
          { title: 'The name it answers as', body: 'Your business name, and a name for the assistant itself if you want callers to have something to refer to.' },
          { title: 'The greeting', body: 'The first line of every call. Worth more attention than anything else here, because it sets what the caller thinks they have reached.' },
          { title: 'The voice', body: 'Tone and character. Pick something plain — an unusually theatrical voice draws attention to itself.' },
          { title: 'Your hours and days', body: 'What counts as open, which shapes what it offers and how it talks about availability.' },
          { title: 'What it knows', body: 'Everything from your website plus anything you upload, which is the real lever on how competent it sounds.' },
          { title: 'What it must not do', body: 'The boundaries. Which questions become a message instead of an answer.' },
        ],
      },
      {
        heading: 'Why the greeting matters most',
        paras: ['It is the only line every single caller hears, and it does three jobs at once: confirms they rang the right place, discloses that this is a virtual assistant, and invites them to say what they want. Get it short and specific and the rest of the call goes better. A long greeting gets talked over, which means the disclosure is missed too.'],
      },
      {
        heading: 'The setting most people neglect',
        paras: ['The boundaries. Deciding what the assistant should refuse to answer is more valuable than any amount of tuning, because a confident wrong answer about your pricing or your policies reaches the caller as fact. Write down the questions where being wrong is expensive, and make those a message and a callback.'],
      },
    ],
    faqs: [
      { q: 'Can I write the greeting myself?', a: 'Yes, and you should — it should sound like your business. Keep it short enough that nobody talks over the disclosure.' },
      { q: 'Can I choose the voice?', a: 'Yes. Pick a plain one rather than a characterful one; the goal is not to be noticed.' },
      { q: 'Can I stop it answering certain questions?', a: 'Yes, and it is the setting worth most of your attention. Anything needing professional judgement should become a message rather than an answer.' },
      { q: 'Can I change things after it is live?', a: 'Yes, from your dashboard, and changes take effect on the next call rather than needing a rebuild.' },
      { q: 'Does it use my business name automatically?', a: 'Yes, and it is picked up during setup along with everything else it learns from your website.' },
    ],
    related: [
      { href: '/learn/how-an-ai-receptionist-learns-your-business', label: 'How it learns your business', sub: 'Website, documents, and gaps.' },
      { href: '/learn/disclosing-ai-to-callers', label: 'Telling callers it is AI', sub: 'What the greeting must include.' },
      { href: '/learn/do-ai-receptionists-sound-human', label: 'Do they sound human?', sub: 'An honest answer.' },
    ],
    ctaHeading: 'Make it sound like your business.',
    ctaSub: 'Set the greeting, the voice and the boundaries before a single caller hears it. Seven days free.',
  },
  {
    slug: 'stop-missing-calls-while-with-a-customer',
    category: 'Guide',
    shortTitle: 'Calls while you are busy',
    metaTitle: 'Stop Missing Calls While You Are With a Customer — Open Lines',
    metaDescription: 'The calls you lose are not the ones after hours, they are the ones during your busiest hour. Why interrupting costs more than it looks, and how to stop choosing.',
    h1: 'Stop missing calls while you are with a customer',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'The worst time to lose a call is the time you are most likely to lose one — mid-appointment, mid-job, hands full. Every option available in that moment is bad: ignore it and lose the work, or answer it and short-change the person in front of you.',
    sections: [
      {
        heading: 'The hidden cost of answering',
        paras: ['Picking up mid-appointment is not free. The customer in the chair notices, the call gets rushed, and the caller hears someone who wants to get off the phone. You have paid twice — once in the experience you just interrupted, and once in the enquiry you handled badly — and you still had to write the details on something.'],
      },
      {
        heading: 'The cost of not answering',
        paras: ['Worse, and invisible. The call rings out, they ring the next business, and you never learn it happened. The losses do not show up anywhere: no voicemail, no missed-call note, nothing to review at the end of the week. That is what makes this specific problem so easy to underestimate for years at a time.'],
      },
      {
        heading: 'What a third option looks like',
        bullets: [
          { title: 'It answers on the third ring', body: 'While your hands are busy, and without you deciding anything.' },
          { title: 'It books into the same calendar', body: 'So the appointment is real, not a note to process later.' },
          { title: 'It marks the urgent ones', body: 'The few that genuinely need you get flagged, so you can step out for those and only those.' },
          { title: 'It tells you afterwards', body: 'One summary per call, read between appointments rather than during one.' },
        ],
      },
      {
        heading: 'Set it up so you still get first refusal',
        paras: ['Forward on no answer rather than forwarding everything. Your phone still rings and you can pick up when you are free; anything you do not reach in a few rings goes to the assistant instead of to nothing. You keep the calls you want and stop losing the ones you cannot take.'],
      },
    ],
    faqs: [
      { q: 'Will my phone still ring?', a: 'Yes, if you set it to forward on no answer. You get first refusal on every call, and only what you do not reach goes to the assistant.' },
      { q: 'How many rings before it picks up?', a: 'You choose, in your carrier’s forwarding settings. Most businesses use three or four — long enough to grab it, short enough that the caller does not give up.' },
      { q: 'Will the caller know I was busy?', a: 'They hear a receptionist answer, not a fault. The assistant discloses that it is virtual, then gets on with helping them.' },
      { q: 'What about calls that really need me?', a: 'Those get flagged as urgent with the caller’s details, so you can step out for the few that warrant it instead of for all of them.' },
    ],
    related: [
      { href: '/learn/ai-receptionist-after-hours', label: 'After-hours answering', sub: 'Where the alternative is silence.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Do I need a new number?', sub: 'No — forward your line.' },
      { href: '/learn/missed-call-text-back', label: 'Missed-call text-back', sub: 'Turn missed calls into jobs.' },
    ],
    ctaHeading: 'Stop choosing between the two.',
    ctaSub: 'Forward on no answer and let it take the ones you cannot. Seven days free, cancel anytime.',
  },
]

export const ARTICLE_SLUGS = ARTICLES.map(a => a.slug)

export function getArticle(slug: string): LearnArticle | undefined {
  return ARTICLES.find(a => a.slug === slug)
}
