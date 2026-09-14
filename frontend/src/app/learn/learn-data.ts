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
        heading: 'Where Open Lines sits on price',
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
        heading: 'How routing works in Open Lines',
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
        heading: 'Two different things get called booking',
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
        heading: 'Measuring a loss that leaves no trace',
        paras: ['You cannot improve what you cannot see, and missed evening calls are invisible by definition — no voicemail, no note, nothing in the morning. Your phone provider’s records are the exception: they show unanswered calls with timestamps, and the evening column is usually the surprise. Pull a month before you start, so the week you run the assistant has something honest to be compared against.'],
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
  {
    slug: 'your-first-week-with-an-ai-receptionist',
    category: 'Guide',
    shortTitle: 'Your first week',
    metaTitle: 'Your First Week With an AI Receptionist: What to Check — Open Lines',
    metaDescription: 'A day-by-day list of what to listen for, what to fix, and the three numbers that tell you whether it is working — before you decide whether to keep it.',
    h1: 'Your first week with an AI receptionist',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Most people set one up, glance at a summary or two, and then decide weeks later on a feeling. A week of deliberate checking gives you an actual answer — and almost everything worth fixing shows up in the first three days.',
    sections: [
      {
        heading: 'Day one: ring it yourself, badly',
        paras: ['Not a clean test call. Mumble, interrupt it halfway through, ask something your website does not answer, change your mind about the time. You are looking for how it behaves when the call goes wrong, because that is the call you will not be there for. Then ring once as a normal customer would, and listen to the greeting as a stranger: does it say who you are, that this is a virtual assistant, and invite them to speak — in under about six seconds?'],
      },
      {
        heading: 'Day two: read every summary, not the bookings',
        paras: ['The bookings are the easy part and they are already in your calendar. The value is in the calls that did not book. Why did they ring? What did the assistant not know? A pattern usually appears within ten summaries, and it is normally three or four questions rather than a systemic problem.'],
      },
      {
        heading: 'Day three: close the gaps you found',
        paras: ['Write the answers to those three or four questions into a short document and upload it. Do not rewrite your website — a page written the way you would answer on the phone is better than a marketing page, and takes twenty minutes. This single step is the difference between an assistant that sounds competent by the end of the week and one that does not.'],
      },
      {
        heading: 'Days four to seven: leave it alone',
        paras: ['Resist tuning. You need a clean run of ordinary calls to judge it, and changing the greeting every day means you are judging four different assistants. Let it work and collect the week.'],
      },
      {
        heading: 'The three numbers at the end',
        bullets: [
          { title: 'Calls answered that previously were not', body: 'Compare against a normal week of missed calls from your phone records. This is the number the whole thing rests on.' },
          { title: 'Bookings it made unaided', body: 'Not enquiries — appointments in your calendar that you did nothing to create.' },
          { title: 'Calls you had to rescue', body: 'Where the assistant got it wrong or the caller needed you. A handful is normal. A majority means your call mix needs a person.' },
        ],
      },
      {
        heading: 'What a bad week actually tells you',
        paras: ['If it booked nothing and every caller wanted something unusual, that is useful information, not a failed experiment: your calls need judgement and an assistant is the wrong tool. Better to learn that in week one than in month six.'],
      },
    ],
    faqs: [
      { q: 'What should I check first?', a: 'Ring it yourself and be a difficult caller — mumble, interrupt, ask something obscure. How it handles a call going wrong matters more than how it handles a clean one.' },
      { q: 'How do I know if it is working?', a: 'Three numbers: calls answered that previously were not, bookings made without you, and calls you had to rescue. The first two against your normal week of missed calls is the answer.' },
      { q: 'Should I keep adjusting it?', a: 'Fix the gaps on day three, then leave it alone. Changing settings daily means you are judging several different assistants rather than one.' },
      { q: 'What if it does badly?', a: 'Read why. Callers wanting things that genuinely need a person is a real finding — it means your call mix is not suited to this, which is worth knowing in week one.' },
    ],
    related: [
      { href: '/learn/how-an-ai-receptionist-learns-your-business', label: 'How it learns your business', sub: 'Closing the gaps you find.' },
      { href: '/learn/is-an-ai-receptionist-worth-it', label: 'Is it worth it?', sub: 'The arithmetic.' },
      { href: '/learn/when-ai-does-not-know-the-answer', label: 'What if it does not know?', sub: 'Why guessing is worse.' },
    ],
    ctaHeading: 'Give it one deliberate week.',
    ctaSub: 'Seven days free is exactly the experiment described above. Cancel anytime before you are charged.',
  },
  {
    slug: 'what-to-do-with-call-summaries',
    category: 'Feature guide',
    shortTitle: 'Using call summaries',
    metaTitle: 'What to Do With AI Call Summaries — Open Lines',
    metaDescription: 'A summary of every call is only useful if it changes something. How to read them for missed revenue, staffing signals and the questions your website should answer.',
    h1: 'What to do with call summaries',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'A summary after every call sounds useful and quickly becomes another inbox nobody reads. The difference is knowing what you are looking for — and it is not the bookings, which are already in your calendar.',
    sections: [
      {
        heading: 'Read the calls that did not book',
        paras: ['Successful bookings need no attention. The information is in the rest: someone who wanted a service you do not offer, who asked a price you no longer charge, who wanted Saturday when you close Fridays. Each of those is either a gap in what the assistant knows or a gap in what you sell, and you cannot tell which until you read a handful together.'],
      },
      {
        heading: 'Four patterns worth watching for',
        bullets: [
          { title: 'The same unanswered question', body: 'Three callers asking about parking means your site should say. This is the cheapest improvement available and it shows up within a week.' },
          { title: 'A service people keep asking for', body: 'Demand you are turning away, in your callers’ own words rather than a survey.' },
          { title: 'Times you cannot offer', body: 'Repeated requests for hours you do not open is a staffing question with evidence attached.' },
          { title: 'Callers who wanted a person', body: 'If this is rising, something in the greeting or the boundaries needs changing.' },
        ],
      },
      {
        heading: 'A ten-minute weekly habit',
        paras: ['Skim only the non-booking summaries from the week. Note anything that appeared twice. Fix the cheapest one — usually an answer to upload. That is the whole routine, it takes ten minutes, and it compounds: each week the assistant handles slightly more of what your callers actually ask.'],
      },
      {
        heading: 'What not to use them for',
        paras: ['Not performance monitoring of your staff, and not a substitute for talking to customers. They are a record of what callers wanted and what happened, which is narrower than it looks — a summary tells you someone asked about pricing, not whether your pricing is right.'],
      },
    ],
    faqs: [
      { q: 'What is in a call summary?', a: 'Who called, what they wanted, how urgent it was, and a suggested next step — plus what was booked if anything was.' },
      { q: 'How do I get them?', a: 'By email after every call, and optionally by text or WhatsApp for the ones you want to know about immediately.' },
      { q: 'Which ones should I actually read?', a: 'The calls that did not result in a booking. Those carry the information; the bookings are already in your calendar.' },
      { q: 'Do I get the full transcript too?', a: 'Yes, in the dashboard, for when a summary is not enough. Most weeks you will not need it.' },
    ],
    related: [
      { href: '/learn/your-first-week-with-an-ai-receptionist', label: 'Your first week', sub: 'What to check, day by day.' },
      { href: '/learn/how-an-ai-receptionist-learns-your-business', label: 'How it learns', sub: 'Turning gaps into answers.' },
      { href: '/learn/ai-receptionist-call-data-privacy', label: 'What happens to call data', sub: 'Retention and deletion.' },
    ],
    ctaHeading: 'Find out what your callers keep asking for.',
    ctaSub: 'A summary after every call, and the patterns inside them. Seven days free, cancel anytime.',
  },
  {
    slug: 'switching-from-an-answering-service',
    category: 'Guide',
    shortTitle: 'Switching services',
    metaTitle: 'Switching From an Answering Service to an AI Receptionist — Open Lines',
    metaDescription: 'How to move without a gap in cover: running both in parallel, what your script does and does not translate to, and the contract terms to check before you give notice.',
    h1: 'Switching from an answering service',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'The risk in switching is not that the new thing fails, it is that you cancel the old one first and discover the gap afterwards. You can run both for a fortnight at almost no cost, and it removes nearly all the risk of the decision.',
    sections: [
      {
        heading: 'Run both, deliberately',
        paras: ['Point your overflow at the new assistant while your existing service keeps handling your main line — or split by time, giving the assistant evenings and weekends first. You get a real comparison on your own calls rather than a demo, and if it is not working you have changed nothing you need to undo.'],
      },
      {
        heading: 'What transfers, and what does not',
        bullets: [
          { title: 'Your script mostly does not', body: 'A script written for a human is a set of instructions for a person who will improvise. An assistant works better from the underlying facts — your services, hours and policies — than from someone else’s wording.' },
          { title: 'Your FAQ answers do', body: 'The document your service used to answer common questions is exactly what to upload. This is the most valuable thing you already own.' },
          { title: 'Your escalation rules do', body: 'Whatever you told them to put through immediately should become the assistant’s urgent-flag rules.' },
          { title: 'Your phone setup does', body: 'You are changing where forwarding points, not changing your number.' },
        ],
      },
      {
        heading: 'Check the contract before you give notice',
        bullets: [
          { title: 'Notice period', body: 'Thirty days is common; some are longer. Start the parallel run before you serve it, not after.' },
          { title: 'Who owns the number', body: 'If they issued you a number you have advertised, find out whether you can port it out. This is the single thing that traps people.' },
          { title: 'Your call records', body: 'Ask for an export before you leave. Afterwards is harder, and sometimes impossible.' },
          { title: 'Minimums already paid', body: 'Prepaid call bundles rarely refund. It may be cheaper to run out the term in parallel.' },
        ],
      },
      {
        heading: 'What you will genuinely miss',
        paras: ['Judgement on difficult calls. A trained person handles an upset caller, an ambiguous situation or an unusual request better than an assistant does, and that will remain true. If a meaningful share of your calls are like that, the honest answer may be keeping a human service for your main line and using an assistant for overflow — rather than switching at all.'],
      },
    ],
    faqs: [
      { q: 'Can I run both at once?', a: 'Yes, and you should. Give the assistant overflow or evenings while your existing service keeps the main line, then compare on your own calls.' },
      { q: 'Will I lose my number?', a: 'Not if it is yours. If your answering service issued the number, check whether you can port it out before giving notice — that is the thing that traps people.' },
      { q: 'Does my script transfer?', a: 'Not directly, and it does not need to. Your FAQ document and escalation rules are the valuable parts; the wording was written for a human who would improvise.' },
      { q: 'What will I miss?', a: 'Judgement on difficult calls. If a lot of your calls need that, keeping a human service for your main line and using an assistant for overflow may beat switching.' },
    ],
    related: [
      { href: '/compare', label: 'Compare the alternatives', sub: 'Including human services.' },
      { href: '/learn/answering-service-cost', label: 'What answering services cost', sub: 'Pricing models compared.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Keeping your number', sub: 'How forwarding works.' },
    ],
    ctaHeading: 'Run it alongside what you have.',
    ctaSub: 'Seven days free, no contract, nothing to cancel first. Compare on your own calls.',
  },
  {
    slug: 'cancellations-and-rescheduling-by-phone',
    category: 'Feature guide',
    shortTitle: 'Cancelling and moving',
    metaTitle: 'Can an AI Receptionist Cancel or Reschedule Appointments? — Open Lines',
    metaDescription: 'Half of appointment calls are not new bookings. What an assistant should do with a cancellation, why a move is not a cancel-and-rebook, and where it must stop.',
    h1: 'Can an AI receptionist cancel or reschedule an appointment?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'It should, because a large share of appointment calls are not new bookings at all — they are people moving or cancelling one. An assistant that only takes new bookings sends the rest to voicemail, which is where the slot you could have resold goes to die.',
    sections: [
      {
        heading: 'Why cancellations are worth handling well',
        paras: ['A cancellation you receive on Tuesday is a slot you can fill. The same cancellation arriving as a voicemail on Thursday, or as a no-show, is lost revenue. Making it easy to cancel sounds like encouraging cancellations; in practice it converts silent no-shows into recoverable gaps, which is strictly better.'],
      },
      {
        heading: 'A move is not a cancel and a rebook',
        paras: ['This distinction matters more than it sounds. If an assistant cancels the old appointment and then fails to create the new one — the slot went, the call dropped, anything — the customer now has no appointment and believes they have one. A proper reschedule treats the move as a single operation and never leaves the caller worse off than when they rang.'],
      },
      {
        heading: 'What it needs to get right',
        bullets: [
          { title: 'Finding the right appointment', body: 'It should list what the caller has and confirm which one, even when there is only one — people book for other people.' },
          { title: 'Keeping the same service', body: 'A move keeps the service. Wanting something different is a new booking, not a reschedule.' },
          { title: 'Keeping the same place', body: 'For a multi-branch business, moving between locations is a different matter and should not be automated quietly.' },
          { title: 'Saying when it is uncertain', body: 'If the outcome is not clear, it must say so, take a contact number and stop — not try again and risk doing it twice.' },
        ],
      },
      {
        heading: 'The changes that need a person',
        paras: ['Late cancellations with a fee attached, anything involving a refund, and moves between branches. Those need a person, or at least a policy decision you have made in advance. An assistant that quietly waives your cancellation fee because nobody told it not to is expensive.'],
      },
    ],
    faqs: [
      { q: 'Can callers cancel an appointment with the AI?', a: 'Yes, on Square Appointments. The cancellation goes into the same calendar as the booking, so the slot is immediately free to resell.' },
      { q: 'Can it move an appointment to a different time?', a: 'Yes — for the same service at the same location. It confirms which appointment first, then offers genuinely available times.' },
      { q: 'Can it move an appointment to another branch?', a: 'Not automatically, by design. It tells the caller your team will arrange that, and takes the details — it will not cancel and rebook to imitate a move.' },
      { q: 'What if something goes wrong mid-change?', a: 'It says so plainly, takes a contact number and stops. It will not retry and risk cancelling an appointment without creating the replacement.' },
      { q: 'Does this work with Google Calendar or Outlook?', a: 'Cancelling and rescheduling by phone is built on Square Appointments. On Google or Outlook the assistant books, and changes are handled by your team.' },
    ],
    related: [
      { href: '/learn/ai-receptionist-book-appointments', label: 'How AI booking works', sub: 'Live availability, real bookings.' },
      { href: '/integrations/square-appointments', label: 'The Square integration', sub: 'Services, staff and branches.' },
      { href: '/learn/reduce-no-shows-with-deposits', label: 'Reducing no-shows', sub: 'Deposits at booking.' },
    ],
    ctaHeading: 'Handle the calls that are not new bookings.',
    ctaSub: 'Cancellations and moves, straight into your Square calendar. Seven days free, cancel anytime.',
  },
  {
    slug: 'handling-busy-periods-and-call-spikes',
    category: 'Guide',
    shortTitle: 'Busy periods and spikes',
    metaTitle: 'Handling Call Spikes and Busy Periods — Open Lines',
    metaDescription: 'Seasonal rushes, a storm, a promotion, one viral post. Why a queue loses more callers than a busy signal, and how to handle a spike without hiring for a peak you have eleven months a year.',
    h1: 'Handling call spikes and busy periods',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Most businesses are not evenly busy. There is a January rush, a storm week, the fortnight after a promotion — and staffing for the peak means paying for it all year, while staffing for the average means losing the peak. This is the specific problem an assistant is unusually good at, because capacity is not the constraint it is for people.',
    sections: [
      {
        heading: 'What a spike actually costs',
        paras: ['Not the calls you answer late — the ones that never reach you. When three people ring at once, two hear ringing or a queue. Queue abandonment is high and fast: most callers with an alternative take it within a minute. On a normal day you might lose one. In a spike week you lose dozens, and they are the calls generated by whatever you just spent money on.'],
      },
      {
        heading: 'Why more than one at a time matters',
        paras: ['A person handles one call. A second caller waits, and waiting is where you lose them. An assistant handles callers independently rather than in a queue, so the second and third are not penalised for arriving at the same moment — which is exactly the failure mode a spike creates.'],
      },
      {
        heading: 'The spikes worth preparing for',
        bullets: [
          { title: 'Seasonal', body: 'Predictable and therefore easy — January for gyms and accountants, spring for landscapers, December for salons.' },
          { title: 'Weather', body: 'Roofers, plumbers and towing firms get a week of demand in a day, with no notice.' },
          { title: 'Marketing', body: 'The calls your campaign generates arrive when the campaign runs, not when you are staffed. Missing them is paying twice.' },
          { title: 'Staff absence', body: 'Not a demand spike but the same effect — normal volume, half the capacity.' },
        ],
      },
      {
        heading: 'Set it up before you need it',
        paras: ['A spike is a bad time to configure anything. Put forward-on-no-answer in place during a quiet week, let it handle the ordinary overflow, and it is already working when the storm arrives. The businesses that get caught are the ones who planned to set it up when things got busy.'],
      },
    ],
    faqs: [
      { q: 'Can it handle more than one caller at a time?', a: 'Yes. Calls are handled independently rather than queued, so a second caller arriving at the same moment is not left waiting behind the first.' },
      { q: 'Is a queue not good enough?', a: 'Rarely. Abandonment is fast — most callers with an alternative take it within about a minute, which is less time than a queue usually takes to clear.' },
      { q: 'What if the spike is genuinely huge?', a: 'It will answer, book what it can and summarise the rest. You still get the details of every caller, which beats a week of calls that left no trace.' },
      { q: 'Should I turn it on only when busy?', a: 'No. Set it up in a quiet week so it is already working when the spike arrives — configuring under pressure is how it gets skipped.' },
    ],
    related: [
      { href: '/learn/stop-missing-calls-while-with-a-customer', label: 'Calls while you are busy', sub: 'The everyday version.' },
      { href: '/learn/ai-receptionist-after-hours', label: 'After-hours answering', sub: 'The other half of the gap.' },
      { href: '/learn/is-an-ai-receptionist-worth-it', label: 'Is it worth it?', sub: 'Work out your own number.' },
    ],
    ctaHeading: 'Be ready before the busy week.',
    ctaSub: 'Set it up while things are quiet and let it take the overflow. Seven days free, cancel anytime.',
  },
  {
    slug: 'ai-receptionist-for-uk-businesses',
    category: 'Guide',
    shortTitle: 'For UK businesses',
    metaTitle: 'AI Receptionist for UK Businesses: Numbers, Rules and Setup — Open Lines',
    metaDescription: 'How UK business numbers differ from Irish ones, what UK GDPR asks of you when calls are recorded, and which number type to pick for a business with one site or several.',
    h1: 'AI receptionist for UK businesses',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'A UK number is straightforward to obtain, which is not true everywhere — Ireland, next door, requires a verified business identity before one is issued at all. What UK businesses do need to think about is which kind of number they want and what happens to the recordings afterwards.',
    sections: [
      {
        heading: 'No verification step, unlike Ireland',
        paras: ['UK numbering is not gated behind a business-identity filing. You can have a number and be answering calls the same day, where an Irish business waits on a regulator before their line exists. If you operate on both sides of the Irish Sea, plan for that difference — the Irish line takes longer to stand up and the UK one does not.'],
      },
      {
        heading: 'Which kind of number to ask for',
        bullets: [
          { title: 'A geographic number', body: 'An 01 or 02 tied to an area. Still the most trusted by callers, and worth having if your customers are local and judge you on it.' },
          { title: 'An 03 number', body: 'Non-geographic but charged at standard rates, so callers pay no more than they would to a landline. Suits a business serving the whole country without pretending to be in one town.' },
          { title: 'A mobile number', body: 'Fine for a sole trader and quietly costly for a business that wants to look established.' },
        ],
      },
      {
        heading: 'What UK GDPR asks once calls are recorded',
        paras: ['A recording of a call is personal data, which brings obligations that have nothing to do with whether recording was allowed: you need a reason for holding it, a period after which it goes, and a way to honour a request to see or delete it. The ICO’s guidance is readable and worth twenty minutes before you start collecting rather than after somebody asks.'],
      },
      {
        heading: 'Two disclosures, not one',
        paras: ['Tell the caller the call is recorded, and tell them they are speaking to an automated system. They are separate things and doing one does not cover the other. Both belong in the opening seconds, before anyone has said anything worth recording.'],
      },
      {
        heading: 'Where a UK business usually gains most',
        paras: ['Trades and clinics with nobody on the phones during the working day, and anyone whose customers ring in the evening because that is when they get home. The pattern is the same everywhere, but UK small businesses are unusually likely to be running the phone off a mobile in a van — which is the setup that loses the most calls.'],
      },
    ],
    faqs: [
      { q: 'Do UK numbers need business verification?', a: 'No. Unlike Ireland, a UK number does not require a business-identity filing before it is issued, so you can be answering calls the same day.' },
      { q: 'Can I keep my existing UK number?', a: 'Yes. Forward it to the number you are issued and callers carry on dialling what they already know.' },
      { q: 'Is call recording legal in the UK?', a: 'Generally yes with appropriate notice, but the recording is personal data under UK GDPR, so you also need a lawful basis, a retention period and a way to handle access and deletion requests.' },
      { q: 'Should I get an 01, 02 or 03 number?', a: 'Geographic 01 and 02 numbers still read as local and trusted. An 03 costs callers the same as a landline and suits a national business. A mobile is fine for a sole trader.' },
      { q: 'Does it work for a business with sites in the UK and Ireland?', a: 'Yes, though allow for the Irish verification step. The UK line can be live immediately while the Irish one is still with the regulator.' },
    ],
    sources: [
      { label: 'UK Information Commissioner’s Office — Guide to UK GDPR', url: 'https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/' },
      { label: 'Ofcom — telephone numbering', url: 'https://www.ofcom.org.uk/phones-and-broadband/phone-numbers/' },
    ],
    related: [
      { href: '/learn/irish-business-phone-number', label: 'Irish numbers and verification', sub: 'Why Ireland is different.' },
      { href: '/learn/call-recording-consent', label: 'Call recording consent', sub: 'Rules by country.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Keeping your number', sub: 'How forwarding works.' },
    ],
    ctaHeading: 'Be answering UK calls today.',
    ctaSub: 'No verification wait, no new number needed. Seven days free, cancel anytime.',
  },
  {
    slug: 'recognising-returning-callers',
    category: 'Feature guide',
    shortTitle: 'Returning callers',
    metaTitle: 'How an AI Receptionist Recognises Returning Callers — Open Lines',
    metaDescription: 'Why greeting someone by name changes a call, what it should and should not reveal to whoever is holding the phone, and the duplicate-record problem it quietly solves.',
    h1: 'Recognising returning callers',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'A caller whose number you already hold does not want to spell their name again. Recognising them makes a call shorter and warmer — and it introduces a question most businesses have never had to think about, which is what a phone number actually proves.',
    sections: [
      {
        heading: 'What recognition changes about a call',
        paras: ['Thirty seconds of a two-minute call is usually identification: name, spelling, phone number, have you been here before. Removing that is not only faster, it changes the register — a caller greeted by name is talking to somewhere that knows them, which is most of what people mean when they say a small business feels personal.'],
      },
      {
        heading: 'The duplicate problem it solves quietly',
        paras: ['Without recognition, every phone booking risks creating a second record for someone you already have. Two records means their history is split across both, reminders go to whichever one was used, and your customer count is wrong. Matching on the number the call arrived from attaches the booking to the person who already exists.'],
      },
      {
        heading: 'A number is not proof of identity',
        bullets: [
          { title: 'Phones get shared', body: 'A household landline, a work mobile, a partner ringing on someone else’s behalf. The number identifies a handset, not a person.' },
          { title: 'Numbers get reassigned', body: 'A mobile number recycled to somebody new should not greet them as your customer of six years.' },
          { title: 'So it greets, it does not disclose', body: 'Using a name is friendly. Reading out an address, a balance or a medical history to whoever happens to be holding that phone is a different thing entirely, and it is the line worth drawing before you need it.' },
        ],
      },
      {
        heading: 'What it should do with a new number',
        paras: ['Take the details and create the record, so the second call is the one that gets recognised. Nothing is lost by not knowing somebody — the assistant simply asks, which is what a receptionist would do.'],
      },
    ],
    faqs: [
      { q: 'How does it know who is calling?', a: 'By the number the call arrives from, matched against the customer records you already hold. A caller it recognises is greeted by name; one it does not is asked.' },
      { q: 'Does it create duplicate customer records?', a: 'It should not, and that is much of the point. Matching an existing customer attaches the booking to them rather than creating a second record with half their history.' },
      { q: 'What if somebody else is using their phone?', a: 'Then the greeting is wrong and nothing worse, which is why a recognised caller should be greeted by name rather than told anything about their account.' },
      { q: 'Can I turn recognition off?', a: 'Yes. Some businesses prefer every caller treated identically, particularly where a shared phone is common.' },
      { q: 'Does it work for withheld numbers?', a: 'No. A withheld or unavailable number cannot be matched, so the caller is treated as new and asked for their details.' },
    ],
    related: [
      { href: '/learn/ai-receptionist-book-appointments', label: 'How AI booking works', sub: 'Live availability, real bookings.' },
      { href: '/learn/ai-receptionist-call-data-privacy', label: 'What happens to call data', sub: 'Retention and deletion.' },
      { href: '/integrations/square-appointments', label: 'Square customer records', sub: 'Where the match happens.' },
    ],
    ctaHeading: 'Stop asking regulars to spell their name.',
    ctaSub: 'Recognised callers, attached to the record you already hold. Seven days free.',
  },
  {
    slug: 'urgent-calls-and-emergencies',
    category: 'Guide',
    shortTitle: 'Urgent calls',
    metaTitle: 'How Should an AI Receptionist Handle Urgent Calls? — Open Lines',
    metaDescription: 'What an assistant should do when a call is genuinely urgent, the one thing it must never be used for, and how to write escalation rules that work at 2am.',
    h1: 'How should an AI receptionist handle urgent calls?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Most calls are routine. The ones that are not are the reason people hesitate to let software answer at all — and that hesitation is reasonable. The answer is not a cleverer assistant, it is a clear set of rules about what it stops doing.',
    sections: [
      {
        heading: 'The line that is not negotiable',
        paras: ['An AI receptionist is not an emergency service and must never be presented as a route to one. It is not a path to 999, 911 or 112, it cannot dispatch anybody, and no configuration makes that safe. If there is any chance your callers might treat your business line as an emergency contact, say so on your website and in your greeting, and make sure everyone on your team understands the same thing.'],
      },
      {
        heading: 'Urgent is not the same as an emergency',
        paras: ['A burst pipe, a locked-out tenant, a dog that has stopped eating, a client whose hearing is tomorrow. None of those is an emergency service matter and all of them need somebody tonight rather than Tuesday. This is the band where an assistant earns its place: recognising the difference and making sure the right person finds out quickly.'],
      },
      {
        heading: 'What it should actually do',
        bullets: [
          { title: 'Recognise urgency from what was said', body: 'Not from a menu. People in trouble do not press two.' },
          { title: 'Take the details that matter', body: 'What has happened, where, and a number that will be answered. A flagged call with no callback number is not useful.' },
          { title: 'Say what happens next, accurately', body: 'A promise of a call within the hour is worth making only if somebody will make it.' },
          { title: 'Flag it so it stands out', body: 'An urgent call buried among twelve routine summaries has not been escalated, it has been filed.' },
        ],
      },
      {
        heading: 'Writing escalation rules that survive 2am',
        paras: ['Write down the handful of things that genuinely mean stop-and-tell-someone, in the words your callers use rather than your own. "No heat" beats "heating system failure". Keep the list short — five or six items — because a long list means everything is urgent and therefore nothing is. Then decide, in advance, who is actually reached and by what: a summary in an inbox nobody opens at 2am is not an escalation path.'],
      },
      {
        heading: 'Be honest with the caller',
        paras: ['If nobody will ring back until morning, the assistant should say so. A caller told the truth can make another plan. A caller promised a call within the hour who gets one at nine the next morning has been let down by you, not by the software.'],
      },
    ],
    faqs: [
      { q: 'Can an AI receptionist handle emergencies?', a: 'No, and it must never be used as one. It is not a route to 999, 911 or 112 and cannot dispatch help. What it can do is recognise urgency, take the details and make sure the right person is told quickly.' },
      { q: 'How does it know a call is urgent?', a: 'From what the caller says, against rules you write in advance — not from a menu, because people in trouble do not press buttons.' },
      { q: 'What should my escalation list contain?', a: 'Five or six things, written in the words your callers actually use. A long list makes everything urgent, which is the same as nothing being urgent.' },
      { q: 'Can it promise someone will ring back?', a: 'Only if someone will. Tell it the truth about your out-of-hours cover so it tells the caller the truth.' },
      { q: 'Can it transfer an urgent call to a person?', a: 'Live transfer depends on your plan and setup. What it can always do is capture the call, flag it, and make sure it is seen ahead of the routine ones.' },
    ],
    related: [
      { href: '/learn/ai-receptionist-after-hours', label: 'After-hours answering', sub: 'Where urgent calls arrive.' },
      { href: '/learn/what-to-do-with-call-summaries', label: 'Using call summaries', sub: 'Spotting what matters.' },
      { href: '/compare', label: 'When to choose a human service', sub: 'Honestly assessed.' },
    ],
    ctaHeading: 'Decide the rules before the call comes.',
    ctaSub: 'Set what counts as urgent and who hears about it. Seven days free, cancel anytime.',
  },
  {
    slug: 'qualifying-leads-on-the-phone',
    category: 'Guide',
    shortTitle: 'Qualifying leads',
    metaTitle: 'What Should an AI Receptionist Ask a New Enquiry? — Open Lines',
    metaDescription: 'The four things worth capturing on a first call, why asking more makes conversion worse, and how to tell a real enquiry from a price-check without interrogating anyone.',
    h1: 'What should it ask a new enquiry?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'A booking is easy — you need a time. An enquiry is harder, because whoever rings back needs enough to be useful and the caller will not sit through a questionnaire. Most businesses ask too much and lose people, or too little and ring back blind.',
    sections: [
      {
        heading: 'The four that nearly always matter',
        bullets: [
          { title: 'What they want', body: 'In their own words, not a category. "The tap in the downstairs loo keeps dripping" tells you more than "plumbing".' },
          { title: 'When', body: 'Today, this week, or some time. This single answer sorts your callbacks better than anything else on the list.' },
          { title: 'Where', body: 'For anything involving travel, before you quote. A job forty minutes away is a different job.' },
          { title: 'A number that will be answered', body: 'And the best time to use it. A callback to a phone in a bag is a callback wasted.' },
        ],
      },
      {
        heading: 'Why asking more costs you',
        paras: ['Every extra question is a chance to hang up. A caller who came to find out if you do something does not expect an intake form, and the fifth question is where they decide to try somebody else. Capture what the callback genuinely needs and leave the rest to the human conversation — that is what the callback is for.'],
      },
      {
        heading: 'Spotting a price-check without being rude',
        paras: ['Some callers are gathering quotes and will not book whatever you say. You can usually tell from how the call opens: a specific problem with a timeframe is a customer, "how much do you charge for X" with no context is often a survey. An assistant should answer the price question honestly, note which kind of call it was, and not spend four questions establishing something you can read in the summary.'],
      },
      {
        heading: 'Where qualification should stop',
        paras: ['Budget, in most trades. Asking what somebody is willing to spend on a first call reads as a filter, and it is — but it is a filter people resent on the phone in a way they do not on a form. Leave it to the conversation with a person, who can raise it once there is a relationship to raise it in.'],
      },
    ],
    faqs: [
      { q: 'What should an AI receptionist ask a new caller?', a: 'What they want in their own words, when they need it, where they are if travel is involved, and a number that will actually be answered. Four things is usually enough for a useful callback.' },
      { q: 'How much qualifying should happen on the call?', a: 'Enough for a useful callback and no more. It can capture what you need and note how serious the enquiry sounded. It should not run an interrogation — every extra question is a chance for the caller to give up.' },
      { q: 'Should it ask about budget?', a: 'Usually not on a first call. It reads as a filter and people resent it on the phone in a way they do not on a form.' },
      { q: 'How do I know which callbacks to do first?', a: 'Timeframe sorts them better than anything else. Someone who needs it today goes ahead of someone thinking about spring.' },
      { q: 'What if the caller will not give details?', a: 'Take what they will give and let them go. A half-captured enquiry is still better than a missed call, and pushing is how you turn a maybe into a no.' },
    ],
    related: [
      { href: '/learn/what-to-do-with-call-summaries', label: 'Using call summaries', sub: 'Turning calls into decisions.' },
      { href: '/learn/urgent-calls-and-emergencies', label: 'Handling urgent calls', sub: 'Sorting what needs you now.' },
      { href: '/learn/customising-your-ai-receptionist', label: 'Setting the boundaries', sub: 'What it asks and what it does not.' },
    ],
    ctaHeading: 'Get enough to ring back usefully.',
    ctaSub: 'Four questions, captured on every enquiry, summarised for you. Seven days free.',
  },
  {
    slug: 'where-should-call-alerts-go',
    category: 'Feature guide',
    shortTitle: 'Choosing an alert channel',
    metaTitle: 'Email, SMS or WhatsApp: Where Should Call Alerts Go? — Open Lines',
    metaDescription: 'Which channel suits which kind of call, why routing everything to your phone stops working within a week, and the mistake that makes people switch alerts off entirely.',
    h1: 'Where should call alerts go?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Every call can reach you by email, text or WhatsApp. The temptation is to send everything everywhere, which works for about four days and then gets muted — at which point you are missing calls again, only now you are paying for it.',
    sections: [
      {
        heading: 'What each channel is actually for',
        bullets: [
          { title: 'Email', body: 'The default, and right for almost everything. It holds detail, it is searchable months later, and nobody feels obliged to react to it at nine at night.' },
          { title: 'Text', body: 'For the small number of calls you would want to be interrupted for. Its value is entirely that it interrupts, which it stops doing the moment it arrives forty times a day.' },
          { title: 'WhatsApp', body: 'Useful where your team already lives in it, and where you want alerts on a phone without them mixing into personal texts.' },
        ],
      },
      {
        heading: 'The mistake almost everyone makes first',
        paras: ['Sending every call by text. Day one it feels responsive. By the end of the week the tone is the same for a booking confirmation and a burst pipe, so you stop looking — and an alert you no longer read is worse than one you never set up, because you believe you are covered.'],
      },
      {
        heading: 'A split that holds up',
        paras: ['Everything by email, and only the urgent by text. That way the record is complete and searchable, while your phone buzzes for the things that genuinely cannot wait. If your phone has not buzzed in a fortnight, your urgency rules are probably too tight — and if it buzzes constantly, they are too loose. Both are worth checking after the first month.'],
      },
      {
        heading: 'One destination is a single point of failure',
        paras: ['If every alert goes to one person’s phone, that person’s holiday is a gap in your cover. Where more than one of you could act on a call, send summaries somewhere shared — a team inbox or a channel — so a call is not waiting on one individual noticing it.'],
      },
    ],
    faqs: [
      { q: 'Can I get a text after every call?', a: 'You can, and most people who do switch it off within a fortnight. Email for everything and text for the urgent ones tends to survive.' },
      { q: 'Which channel should I choose?', a: 'Email for the record, text for interruption, WhatsApp if your team already works there. The right answer is usually more than one channel doing different jobs.' },
      { q: 'Can different calls go to different places?', a: 'That is the setup worth aiming for — everything by email, only what is urgent by text, so interruption still means something.' },
      { q: 'Can alerts go to more than one person?', a: 'Sending summaries somewhere shared is worth doing if more than one of you could act on a call. One person’s phone is one person’s holiday away from a gap.' },
      { q: 'Do callers get anything?', a: 'Yes — a confirmation of what was booked, separately from the summary that comes to you.' },
    ],
    related: [
      { href: '/learn/what-to-do-with-call-summaries', label: 'Using call summaries', sub: 'What to read and what to skip.' },
      { href: '/learn/urgent-calls-and-emergencies', label: 'Handling urgent calls', sub: 'What should interrupt you.' },
      { href: '/integrations/slack', label: 'Summaries in Slack', sub: 'For teams already there.' },
    ],
    ctaHeading: 'Set it up so you still read the alerts.',
    ctaSub: 'Email for the record, text for the urgent. Seven days free, cancel anytime.',
  },
  {
    slug: 'booking-with-a-specific-team-member',
    category: 'Feature guide',
    shortTitle: 'Booking a named person',
    metaTitle: 'Can a Caller Book With a Specific Person? — Open Lines',
    metaDescription: 'Why "I want Sarah" is the request that breaks most booking systems, how per-staff availability works, and what should happen when the person they asked for is fully booked.',
    h1: 'Can a caller book with a specific person?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'In any business where customers have a favourite — a stylist, a barber, a therapist, a mechanic they trust — "can I have Sarah?" is one of the most common things said on the phone. It is also the request that quietly breaks booking systems, because a slot being free is not the same as Sarah being free.',
    sections: [
      {
        heading: 'Why business availability is the wrong answer',
        paras: ['A calendar with three staff and one open chair at two o’clock is available — but not if the caller wants the person who is already busy. Offering that slot produces a booking somebody has to ring back and undo, which costs more goodwill than saying no would have. The availability that matters is the named person’s, not the business’s.'],
      },
      {
        heading: 'How a named booking should work',
        bullets: [
          { title: 'Your team list comes across', body: 'When you connect Square Appointments, the team members come with it, so the assistant knows Sarah is a real person rather than a word in the sentence.' },
          { title: 'It checks that person', body: 'Availability is read for the individual, so the times offered are ones they can actually take.' },
          { title: 'It handles the service too', body: 'Not everyone does everything. If a treatment is only offered by two of your four staff, asking for a third should not produce a booking.' },
          { title: 'And the right branch', body: 'A named person works somewhere. Across several sites, availability has to mean that person at that location.' },
        ],
      },
      {
        heading: 'What to do when they are fully booked',
        paras: ['This is the interesting part, and it is a business decision rather than a technical one. Some businesses want the caller offered the next availability with that person even if it is a fortnight away, because the relationship is the product. Others would rather offer somebody else this week. Both are defensible and the assistant should do whichever you chose — the failure is doing neither and simply saying no.'],
      },
      {
        heading: 'The request behind the request',
        paras: ['A caller asking for a name is usually asking for continuity — somebody who knows their hair, their car, their history. Where that person has genuinely gone, being told plainly beats being quietly booked with a stranger and finding out on arrival.'],
      },
    ],
    faqs: [
      { q: 'Can a caller ask for a specific stylist or therapist by name?', a: 'Yes, where your booking system holds per-person availability. On Square Appointments your team members come across when you connect, so the assistant checks that individual rather than the business.' },
      { q: 'What if that person is fully booked?', a: 'That is your call to make in advance: offer their next availability, or offer a colleague sooner. The assistant should do what you decided rather than simply refusing.' },
      { q: 'Does it know who does which service?', a: 'Where your system records it, yes. A treatment only two of your staff offer should not be bookable with the other two.' },
      { q: 'Can I do this on a shared Google Calendar?', a: 'Not by name. A single shared calendar tells the assistant the business is free, not which of your staff is — per-person availability comes from Square Appointments.' },
    ],
    related: [
      { href: '/integrations/square-appointments', label: 'The Square integration', sub: 'Services, staff and branches.' },
      { href: '/learn/ai-receptionist-book-appointments', label: 'How AI booking works', sub: 'Live availability, real bookings.' },
      { href: '/multi-location', label: 'Several branches?', sub: 'The right person at the right site.' },
    ],
    ctaHeading: 'Let callers ask for who they always ask for.',
    ctaSub: 'Per-person availability, booked into your Square calendar. Seven days free.',
  },
  {
    slug: 'uploading-documents-your-ai-can-answer-from',
    category: 'Feature guide',
    shortTitle: 'Uploading documents',
    metaTitle: 'Teaching an AI Receptionist From Your Own Documents — Open Lines',
    metaDescription: 'What to upload, what not to, why a photographed price list works, and the one-page document that fixes most unanswered questions in twenty minutes.',
    h1: 'Uploading documents your AI can answer from',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Your website is marketing. Your answers are somewhere else — in a price list, a policy, an email you have sent forty times. Getting those in front of the assistant is the cheapest improvement available, and it takes about twenty minutes.',
    sections: [
      {
        heading: 'What is worth uploading',
        bullets: [
          { title: 'Your real price list', body: 'Including the caveats. "From £120, more for long hair" is the answer people actually want and the one websites rarely give.' },
          { title: 'Policies you repeat', body: 'Cancellations, deposits, lateness, what to bring. These generate more calls than anything else and have fixed answers.' },
          { title: 'Aftercare and preparation notes', body: 'What to do before an appointment and after one. Callers ask, and the answer never changes.' },
          { title: 'The email you always send', body: 'If your team has a stock reply to a common question, that is already the document. Upload it as it is.' },
        ],
      },
      {
        heading: 'A photograph is fine',
        paras: ['A scanned or photographed price list is read the same way a typed one is, which matters because the businesses with the best answers on paper are usually the ones least likely to have them in a document. A clear photo of the board on the wall beats retyping it, and beats not doing it at all.'],
      },
      {
        heading: 'What not to upload',
        bullets: [
          { title: 'Anything with customer details in it', body: 'A spreadsheet of past bookings is not reference material, and putting it where an assistant can read from it is asking for an answer nobody should hear.' },
          { title: 'Contracts and staff documents', body: 'Nothing a caller could ever need is in there.' },
          { title: 'Anything out of date', body: 'An old price list will be quoted confidently. Delete it rather than leaving it alongside the new one.' },
        ],
      },
      {
        heading: 'The twenty-minute version',
        paras: ['If you do nothing else: open a blank document, write the ten questions your team answers most, answer them the way you would on the phone, and upload it. It will outperform a rewritten website, because it is written in the register callers ask in rather than the register websites are written in.'],
      },
    ],
    faqs: [
      { q: 'Does a photo of my price list work?', a: 'Yes. Scanned and photographed pages are read the same way typed files are, which matters because the best answers are usually the ones that only exist on paper.' },
      { q: 'What should I upload first?', a: 'Your real price list with its caveats, and your cancellation and deposit policies. Those account for most repeated questions.' },
      { q: 'Should I upload customer records?', a: 'No. Reference material only. Anything containing customer details does not belong somewhere an assistant can read from it aloud.' },
      { q: 'What if a document goes out of date?', a: 'Remove it rather than leaving it next to the new one. An old price list will be quoted with complete confidence.' },
      { q: 'Is a document better than updating my website?', a: 'Usually, and faster. Write the answers the way you would say them on the phone — websites are written in a different register from the one callers ask in.' },
    ],
    related: [
      { href: '/learn/how-an-ai-receptionist-learns-your-business', label: 'How it learns your business', sub: 'Website, documents and gaps.' },
      { href: '/learn/when-ai-does-not-know-the-answer', label: 'What if it does not know?', sub: 'Why guessing is worse.' },
      { href: '/learn/what-to-do-with-call-summaries', label: 'Finding the gaps', sub: 'From your own calls.' },
    ],
    ctaHeading: 'Twenty minutes, ten answers.',
    ctaSub: 'Upload what your website does not say and hear the difference the same week. Seven days free.',
  },
  {
    slug: 'call-transcripts-and-what-they-show',
    category: 'Feature guide',
    shortTitle: 'Reading transcripts',
    metaTitle: 'Call Transcripts: When to Read One and What to Look For — Open Lines',
    metaDescription: 'Summaries are for most days. A transcript is for the handful of calls that went wrong — what to look for in one, and the three you should read in your first fortnight.',
    h1: 'When should you read a call transcript?',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Almost never, and that is the point. A summary answers what happened. A transcript answers why it happened that way, which you only need when the summary has surprised you — but on those calls it is the difference between a theory and an explanation.',
    sections: [
      {
        heading: 'The three worth reading in your first fortnight',
        bullets: [
          { title: 'The first booking it made alone', body: 'Not to check it worked — to hear how the assistant talks about your business when nobody is watching. This is the call that tells you whether the greeting and the tone are right.' },
          { title: 'A call that ended without a booking', body: 'Where the caller wanted something and left without it. The moment it went wrong is usually visible and usually fixable.' },
          { title: 'Any call somebody complained about', body: 'Before responding. A transcript turns "your robot was useless" into a specific sentence you can do something about.' },
        ],
      },
      {
        heading: 'The three patterns behind most bad calls',
        paras: ['Where the caller repeated themselves, which means they were not understood the first time. Where the assistant gave a long answer to a short question. Where it hesitated on something your website should have said. Those three patterns account for most disappointing calls, and all three are fixed by adding knowledge rather than by changing settings.'],
      },
      {
        heading: 'What a transcript is not for',
        paras: ['Reading everything. A business doing thirty calls a week that reads thirty transcripts has replaced answering the phone with reading about answering the phone, which is worse. The summaries exist so you do not have to, and the transcript is there for the exception.'],
      },
      {
        heading: 'Treat them as sensitive',
        paras: ['A transcript contains whatever the caller volunteered, which is often more than they meant to. It is personal data, it has a retention period, and it should not be forwarded around casually — a summary usually conveys everything a colleague actually needs.'],
      },
    ],
    faqs: [
      { q: 'Can I read the full transcript of a call?', a: 'Yes, in the dashboard. Most weeks you will not need to — the summary carries what you need and the transcript is for the exceptions.' },
      { q: 'Which calls are worth reading in full?', a: 'The first booking it made unaided, one that ended without a booking, and any call somebody complained about.' },
      { q: 'What should I look for in a transcript?', a: 'Repetition, over-long answers, and hesitation on things your website should say. All three are fixed by adding knowledge rather than changing settings.' },
      { q: 'Should transcripts be shared with the team?', a: 'Sparingly. They contain whatever the caller volunteered, and the summary usually tells a colleague everything they need.' },
    ],
    related: [
      { href: '/learn/what-to-do-with-call-summaries', label: 'Using call summaries', sub: 'What to read most days.' },
      { href: '/learn/ai-receptionist-call-data-privacy', label: 'What happens to call data', sub: 'Retention and deletion.' },
      { href: '/learn/your-first-week-with-an-ai-receptionist', label: 'Your first week', sub: 'What to check, day by day.' },
    ],
    ctaHeading: 'See exactly what was said, when it matters.',
    ctaSub: 'Summaries for every call, transcripts for the ones that need them. Seven days free.',
  },
  {
    slug: 'keeping-your-ai-answers-current',
    category: 'Feature guide',
    shortTitle: 'Keeping answers current',
    metaTitle: 'Keeping an AI Receptionist Up to Date — Open Lines',
    metaDescription: 'Prices change and nobody tells the phone. What goes stale, why holiday hours are the classic failure, and how re-crawling keeps answers aligned without anyone remembering.',
    h1: 'Keeping your AI receptionist up to date',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'The assistant knows what you told it in week one. Your business has moved on since — a price rose, a service stopped, you closed for two weeks in August. Nothing announces these changes to your phone, which is how a confident wrong answer ends up being given for months.',
    sections: [
      {
        heading: 'What actually goes stale',
        bullets: [
          { title: 'Prices', body: 'The most quoted and the most changed. A rise announced on your website in March is still being undercut on the phone in June if nothing re-read it.' },
          { title: 'Holiday and seasonal hours', body: 'The classic failure. Nobody updates the assistant for a bank holiday, and it books people in for a day you are shut.' },
          { title: 'Services you stopped', body: 'Worse than a wrong price, because the customer arrives expecting something you no longer do.' },
          { title: 'People who left', body: 'A caller asking for someone by name should not be offered their availability.' },
        ],
      },
      {
        heading: 'Why automatic beats remembering',
        paras: ['Every business intends to keep this current and none reliably does, because the moment you change a price is the moment you are busy changing a price. Re-reading your website on a schedule removes the step that gets skipped: you edit the page you were already editing, and the phone catches up without a second task existing.'],
      },
      {
        heading: 'What a schedule cannot catch',
        paras: ['Anything that was never on your website. If your August closure lives only in a group chat, no amount of re-crawling will find it. Things that exist only in someone’s head need to be written down once — which is a good argument for keeping a short uploaded document alongside the site, and updating that when reality changes.'],
      },
      {
        heading: 'A five-minute quarterly check',
        paras: ['Ring your own number and ask three things: your most expensive service and its price, whether you do something you stopped doing, and your opening hours for next Monday. If all three are right, your knowledge is current. If any is wrong, you have found it before a customer did.'],
      },
    ],
    faqs: [
      { q: 'Does it update itself when I change my website?', a: 'Scheduled re-crawling keeps it aligned with your site without anyone remembering to trigger it, so editing the page is the only step.' },
      { q: 'What about things not on my website?', a: 'Those need writing down once — a short uploaded document alongside the site, updated when reality changes. A crawl cannot find what was never published.' },
      { q: 'What goes out of date fastest?', a: 'Prices and holiday hours. Both get changed quietly, and both produce a confident wrong answer for months if nothing re-reads them.' },
      { q: 'How do I check it is current?', a: 'Ring your own number quarterly and ask three things: a price, something you stopped doing, and next Monday’s hours. Five minutes, and you find errors before a customer does.' },
    ],
    related: [
      { href: '/learn/uploading-documents-your-ai-can-answer-from', label: 'Uploading documents', sub: 'For what your site does not say.' },
      { href: '/learn/how-an-ai-receptionist-learns-your-business', label: 'How it learns', sub: 'Where the answers come from.' },
      { href: '/learn/when-ai-does-not-know-the-answer', label: 'What if it does not know?', sub: 'Why guessing is worse.' },
    ],
    ctaHeading: 'Change the page, not the phone.',
    ctaSub: 'Scheduled re-crawling keeps answers aligned with your site. Seven days free.',
  },
  {
    slug: 'answering-calls-while-driving-between-jobs',
    category: 'Common problem',
    shortTitle: 'Calls while on the road',
    metaTitle: 'Missing Calls While Driving Between Jobs — Open Lines',
    metaDescription: 'Trades and mobile businesses lose work to the van, the ladder and the customer’s kitchen. Why voicemail does not fix it and what answering every call actually changes.',
    h1: 'Missing calls while driving between jobs',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'If your work happens in other people’s homes, your phone rings at the worst possible moments: mid-job, up a ladder, hands in a boiler, or doing seventy on a motorway. The call you cannot take is rarely a small one — it is usually somebody who found three numbers and is working down the list.',
    sections: [
      {
        heading: 'Why this is worse than it looks',
        paras: ['A missed call in a shop is a customer who might come back. A missed call in the trades is a customer who has already rung the next name on the search results before you have parked. The work does not wait for you to be free, and the people who ring at nine in the morning have usually decided by half past.'],
      },
      {
        heading: 'Why voicemail does not rescue it',
        paras: ['Most people will not leave one. Those who do leave a name and half a number, and you ring back at seven in the evening when they are making dinner and have already booked someone. Voicemail records that you lost the job; it does not stop you losing it.'],
      },
      {
        heading: 'What answering actually changes',
        bullets: [
          { title: 'You stop losing the easy ones', body: 'A good share of calls are simple — do you cover this area, do you do this kind of work, roughly what does it cost. Those are answerable without you.' },
          { title: 'Details arrive intact', body: 'Address, the nature of the problem, when they are in. Written down, in a summary, instead of half-remembered from a hands-free call in traffic.' },
          { title: 'Your evenings stop being admin', body: 'Returning six calls after dinner is unpaid work you do while tired. Most of them did not need you.' },
          { title: 'Urgency gets separated from noise', body: 'A leak and a quote request should not reach you the same way. Knowing which is which as it happens is the difference between reacting and catching up.' },
        ],
      },
      {
        heading: 'The calls that still need you',
        paras: ['Quoting a job you have not seen, judging whether something is an emergency, agreeing a price that depends on what is behind the wall. Nobody should be doing those for you. The point is arriving at them with the address, the problem and the availability already captured, instead of starting from a missed-call notification.'],
      },
    ],
    faqs: [
      { q: 'I am on the road all day — can this actually help?', a: 'That is the case it fits best. Calls that arrive while you are driving or mid-job get answered, the details are captured, and you see them when you stop rather than chasing missed numbers at seven in the evening.' },
      { q: 'Can it tell an emergency from a quote request?', a: 'It can capture what the caller describes and flag it, so the two do not reach you the same way. Judging whether something is a genuine emergency stays yours.' },
      { q: 'Will it quote for a job?', a: 'It can give the prices you have set. Anything that depends on seeing the work should come to you — quoting blind is how trades lose money.' },
      { q: 'Do I need a new number?', a: 'No. You can forward your existing number so customers keep ringing the one they already have.' },
    ],
    related: [
      { href: '/learn/is-an-ai-receptionist-worth-it', label: 'What a missed call costs', sub: 'The arithmetic nobody does.' },
      { href: '/learn/missed-call-text-back', label: 'Missed calls and text-backs', sub: 'Why voicemail rarely saves one.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Keeping your number', sub: 'Forwarding, not porting.' },
    ],
    ctaHeading: 'The van is not a reception desk.',
    ctaSub: 'Every call answered, every detail written down, waiting for you when you stop. Seven days free.',
  },
  {
    slug: 'covering-the-phone-during-staff-holidays',
    category: 'Common problem',
    shortTitle: 'Holiday and sickness cover',
    metaTitle: 'Covering the Phone During Staff Holidays and Sickness — Open Lines',
    metaDescription: 'August, half-term and the winter flu week. Why temporary cover is the hardest kind to arrange, and what standing cover changes about how those weeks run.',
    h1: 'Covering the phone when staff are away',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Every small business has weeks where the phone is nobody’s job. Somebody is on holiday, somebody else is off sick, and the person who normally answers is doing two roles. The phone is the first thing to slip, because it is the only task that interrupts every other one.',
    sections: [
      {
        heading: 'Why cover is hard to arrange',
        paras: ['Temporary help costs the most per hour and delivers the least, because whoever you bring in does not know your prices, your regulars or the answer to the question you get twenty times a week. Agencies want a minimum. Training somebody for two weeks costs more than the two weeks are worth. So in practice most businesses do not arrange cover at all — they absorb it, and the absorbing shows.'],
      },
      {
        heading: 'What the absorbed version looks like',
        bullets: [
          { title: 'Calls ring out at the busy hours', body: 'Precisely when the remaining staff are dealing with people in front of them.' },
          { title: 'Bookings get taken on paper', body: 'And entered later, or not, which produces the double-booking you discover on the day.' },
          { title: 'The backlog outlives the absence', body: 'The week after a holiday is spent catching up on the week of it.' },
        ],
      },
      {
        heading: 'Standing cover instead of temporary cover',
        paras: ['The alternative is not hiring for the gap but having something that is always there and simply matters more in those weeks. It knows your prices in August because it knew them in July. Bookings go into the same calendar whether your receptionist is at their desk or in Spain, so there is no re-entry and no backlog on their return.'],
      },
      {
        heading: 'It also covers the smaller gaps',
        paras: ['Holidays are the obvious case, but the everyday ones add up faster: lunch, the school run, a staff meeting, the twenty minutes where everyone is with a customer. Those are the same problem in smaller units, and they happen every week rather than twice a year.'],
      },
    ],
    faqs: [
      { q: 'Can I use this only for holiday weeks?', a: 'You can, but it works better as standing cover — it knows your prices in August because it knew them in July, and there is no setting-up scramble the week before someone leaves.' },
      { q: 'Is it cheaper than temporary cover?', a: 'Almost always. Temporary help costs the most per hour and knows the least about your business, which is why most places absorb the gap instead of covering it.' },
      { q: 'What happens to bookings taken while my receptionist is away?', a: 'They go into the same calendar they always do, so there is no paper pile to re-enter and no backlog waiting on their return.' },
      { q: 'Does it help with lunch breaks and the school run?', a: 'Those are the same gap in smaller units, and they happen every week rather than twice a year.' },
    ],
    related: [
      { href: '/learn/answering-service-cost', label: 'Versus an answering service', sub: 'Messages or bookings.' },
      { href: '/learn/receptionist-salary-vs-ai-receptionist', label: 'Salary versus software', sub: 'What cover really costs.' },
      { href: '/learn/ai-receptionist-after-hours', label: 'After-hours calls', sub: 'The other gap.' },
    ],
    ctaHeading: 'August should not cost you bookings.',
    ctaSub: 'Cover that is already trained, because it was there in July. Seven days free.',
  },
  {
    slug: 'receptionist-salary-vs-ai-receptionist',
    category: 'Cost guide',
    shortTitle: 'Salary comparison',
    metaTitle: 'Receptionist Salary vs an AI Receptionist: an Honest Comparison — Open Lines',
    metaDescription: 'The real cost of a front-desk hire including employer costs and cover, what an AI receptionist costs instead, and the things a person does that no software replaces.',
    h1: 'Receptionist salary vs an AI receptionist',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'This comparison is usually done dishonestly, in both directions. Software companies compare a salary to a subscription and declare victory; the people who have actually employed a receptionist know the roles are not the same. Here is the version worth reading before you decide.',
    sections: [
      {
        heading: 'What a front-desk hire really costs',
        paras: ['Not the salary. Employer contributions, holiday pay, sick pay, pension, recruitment, and the training weeks before they are useful. A part-time front desk lands well above the headline figure, and that is before the structural problem: you are buying a fixed number of hours, and your calls do not arrive in a flat line across them.'],
      },
      {
        heading: 'What you are buying with each',
        bullets: [
          { title: 'A person covers about forty hours', body: 'And never the evening, the weekend or the fortnight they are away. Calls outside those hours are not covered at any price.' },
          { title: 'Software covers all of them', body: 'Including the three-o’clock Sunday call, which is exactly where the missed bookings concentrate.' },
          { title: 'A person handles ambiguity', body: 'The upset customer, the complicated exception, the thing that needs judgment. This is not a small category and it does not go away.' },
          { title: 'Software handles repetition', body: 'Opening hours, prices, parking, availability, booking. Which is most of the volume and none of the interest.' },
        ],
      },
      {
        heading: 'The honest conclusion',
        paras: ['If your phone is genuinely busy and your customers need real conversations, a receptionist is a good hire and software is a supplement. If your volume is thirty or fifty calls a week, mostly repetitive, spread across hours a person would not be there for, then a hire is an expensive way to answer questions a document could answer — and the comparison tilts hard the other way.'],
      },
      {
        heading: 'The combination most places land on',
        paras: ['Not replacement. The assistant takes the overflow, the after-hours and the repetition; the person does the front desk, the difficult calls and the customers standing in front of them. That arrangement is usually cheaper than a second hire and better than either alone.'],
      },
    ],
    faqs: [
      { q: 'Is an AI receptionist cheaper than hiring someone?', a: 'Substantially, on cost per hour covered — but they are not the same product. A person handles judgment and upset customers; software handles repetition and the hours nobody is there.' },
      { q: 'Should I replace my receptionist?', a: 'Usually not. Most businesses end up with both: the assistant takes overflow, after-hours and repeat questions, and the person does the front desk and the difficult calls.' },
      { q: 'What does a receptionist actually cost?', a: 'Well above the salary once employer contributions, holiday and sick pay, pension, recruitment and the training weeks are counted — and you are buying fixed hours your calls do not arrive in.' },
      { q: 'When is hiring clearly the right answer?', a: 'When the phone is genuinely busy with conversations that need judgment. Repetitive volume spread across evenings and weekends is the case where a hire is an expensive fit.' },
    ],
    related: [
      { href: '/pricing', label: 'What it costs', sub: 'Plans and minutes.' },
      { href: '/learn/covering-the-phone-during-staff-holidays', label: 'Holiday cover', sub: 'The hardest weeks.' },
      { href: '/learn/answering-service-cost', label: 'Versus an answering service', sub: 'The third option.' },
    ],
    ctaHeading: 'Run the comparison on your own numbers.',
    ctaSub: 'Seven days free, no commitment, and you will know within a week.',
  },
  {
    slug: 'cost-per-booked-appointment',
    category: 'Cost guide',
    shortTitle: 'Cost per booking',
    metaTitle: 'Cost Per Booked Appointment: the Number That Settles It — Open Lines',
    metaDescription: 'Monthly cost is the wrong measure. How to work out what each recovered booking costs you, why the first one usually pays for the month, and when the answer is no.',
    h1: 'The only number that settles it: cost per booking',
    published: '2026-09-14',
    updated: '2026-09-14',
    intro: 'Arguments about whether software is worth it usually stall on the monthly price, which is the least informative number available. The figure that decides it is what each booking you would otherwise have lost ends up costing — and unlike most marketing arithmetic, you can work it out from things you already know.',
    sections: [
      {
        heading: 'The calculation',
        paras: ['Take your monthly cost. Divide it by the number of bookings that came in through calls you would not have answered — evenings, weekends, the hours you were with customers. That is your cost per recovered booking. Compare it against what a booking is worth to you, and the decision makes itself in one line.'],
      },
      {
        heading: 'Why it usually looks decisive',
        paras: ['For most appointment businesses, one recovered booking a month covers the subscription outright, because the average job is worth more than the plan. A salon at seventy pounds a head, a clinic at ninety, a trade at a couple of hundred — in each case the first recovered booking clears the cost and everything after it is margin. The arithmetic is unusual in being this blunt.'],
      },
      {
        heading: 'Count the repeat value too, carefully',
        paras: ['A new customer in most of these businesses is not worth one appointment; they are worth however many times they come back. That materially changes the figure — but it is also where cost-per-booking arguments become dishonest, so use your real repeat rate rather than the optimistic one, and be willing to reach the answer that says no.'],
      },
      {
        heading: 'When the number says no',
        bullets: [
          { title: 'Very low call volume', body: 'A handful of calls a month means very little to recover, whatever the value of each one.' },
          { title: 'Low-value, one-off jobs', body: 'If a booking is worth fifteen pounds and never repeats, the arithmetic is much tighter and may not clear.' },
          { title: 'Calls that are never bookings', body: 'Businesses whose phone is mostly support or suppliers are solving a different problem than this one.' },
        ],
      },
      {
        heading: 'How to get the real figure',
        paras: ['Run it for a week and look at what actually came in outside your open hours, then annualise. A week of your own calls beats any industry benchmark, and it is the difference between a decision and a guess.'],
      },
    ],
    faqs: [
      { q: 'How do I work out cost per booked appointment?', a: 'Divide your monthly cost by the bookings that came from calls you would otherwise have missed — evenings, weekends, and the hours you were busy. Compare that against what a booking is worth to you.' },
      { q: 'How many recovered bookings does it take to break even?', a: 'For most appointment businesses, one a month. The average job is worth more than the plan, so the first recovered booking clears the cost.' },
      { q: 'Should I count repeat custom?', a: 'Yes, but with your real repeat rate rather than an optimistic one. It changes the figure a lot, which is exactly why it is the number people inflate.' },
      { q: 'When does the arithmetic not work?', a: 'Very low call volume, low-value jobs that never repeat, or a phone that is mostly suppliers and support rather than potential bookings.' },
      { q: 'What is the fastest way to know?', a: 'Run it for a week and count what came in outside your open hours. Your own week beats any benchmark.' },
    ],
    related: [
      { href: '/learn/stop-missing-calls-while-with-a-customer', label: 'Calls missed while busy', sub: 'Where the recovery comes from.' },
      { href: '/pricing', label: 'What it costs', sub: 'Plans and minutes.' },
      { href: '/learn/receptionist-salary-vs-ai-receptionist', label: 'Versus hiring', sub: 'The other comparison.' },
    ],
    ctaHeading: 'Work it out on a real week.',
    ctaSub: 'Seven days free. Count what comes in after hours and decide from your own numbers.',
  },
  {
    slug: 'what-your-calls-are-telling-you',
    category: 'Feature guide',
    shortTitle: 'Insights from calls',
    metaTitle: 'What Your Calls Are Telling You — Open Lines',
    metaDescription: 'Your phone is the best research your business has and nobody reads it. What patterns across calls reveal, and why a finding from four calls should not be called a trend.',
    h1: 'What your calls are telling you',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'Every week your phone produces a detailed record of what people want, what confuses them, and where they give up. Almost no small business reads it, because reading it means listening to forty calls. Patterns across calls are visible without doing that, and they are usually more useful than any single call.',
    sections: [
      {
        heading: 'The patterns that pay for themselves',
        bullets: [
          { title: 'Questions with no answer on your site', body: 'If eleven people asked about parking and your website never mentions it, that is eleven calls you did not need to receive and a paragraph you can write in two minutes.' },
          { title: 'Services people ask for that you do not offer', body: 'A steady trickle of requests for something adjacent to your work is market research you did not commission.' },
          { title: 'When the calls actually arrive', body: 'Most owners are wrong about their own peak hour. Knowing it changes staffing more than any advice ever will.' },
          { title: 'Where conversations stop', body: 'Enquiries that consistently end at the same point — a price, a wait time, an availability gap — are pointing at something specific.' },
        ],
      },
      {
        heading: 'Why sample size is on every finding',
        paras: ['Four calls is not a trend, and software that says otherwise will send you redecorating on the strength of one bad morning. Findings carry the number of calls behind them, so you can tell the difference between a pattern worth acting on and a coincidence with a confident sentence wrapped around it.'],
      },
      {
        heading: 'What gets excluded on purpose',
        paras: ['Test calls, wrong numbers and telemarketers are identified and kept out of the figures. It matters more than it sounds: counting a robocall as a lost enquiry drags your conversion rate down and makes every number above it fiction. A conversion rate that includes junk is not a measurement of anything.'],
      },
      {
        heading: 'How to use it without overreacting',
        paras: ['Once a month, not daily. Take the finding with the largest number behind it, do the one thing it suggests, and leave the rest. The businesses that get value from this act on one thing a month; the ones that get nothing act on everything for a fortnight and then stop opening it.'],
      },
    ],
    faqs: [
      { q: 'What can call data tell me about my business?', a: 'The questions your website fails to answer, services people ask for that you do not offer, when your calls actually arrive, and the point where enquiries consistently stop.' },
      { q: 'How do I know a finding is real?', a: 'Each one carries the number of calls behind it. Four calls is not a trend, and anything presented as one without a sample size should be ignored.' },
      { q: 'Are junk calls counted?', a: 'No. Test calls, wrong numbers and telemarketers are identified and excluded, because counting a robocall as a lost enquiry makes your conversion rate fiction.' },
      { q: 'How often should I look at it?', a: 'Monthly. Act on the single finding with the most evidence behind it and leave the rest — that is the pattern that actually changes businesses.' },
    ],
    related: [
      { href: '/learn/what-to-do-with-call-summaries', label: 'Using call summaries', sub: 'The day-to-day version.' },
      { href: '/learn/spam-and-nuisance-calls', label: 'Junk calls', sub: 'What happens to them.' },
      { href: '/learn/keeping-your-ai-answers-current', label: 'Closing the gaps', sub: 'Turning findings into answers.' },
    ],
    ctaHeading: 'Your phone already did the research.',
    ctaSub: 'See the patterns across your calls, with the evidence attached. Seven days free.',
  },
  {
    slug: 'deposits-for-group-bookings',
    category: 'Feature guide',
    shortTitle: 'Group deposits',
    metaTitle: 'Taking Deposits for Group Bookings by Phone — Open Lines',
    metaDescription: 'A party of eight that does not turn up costs eight times as much. How per-person deposits work, how to pick an amount, and why groups are the booking worth protecting most.',
    h1: 'Deposits for group bookings',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'A single no-show costs you one slot. A party of eight that evaporates costs you the whole evening, and you usually find out an hour before, when nobody else can fill it. Groups are the bookings most worth protecting and the ones businesses most often take on trust.',
    sections: [
      {
        heading: 'Why groups behave differently',
        paras: ['Nobody in a group of eight feels individually responsible for the booking. One person made it, the rest half-remember it, and the plan dissolves in a message thread you are not in. That is not bad faith — it is what happens when commitment is spread across people who never spoke to you.'],
      },
      {
        heading: 'Per-person rather than flat',
        paras: ['A flat deposit does not scale with what is at risk: twenty-five pounds is a reasonable hold on a table for two and a rounding error on a table for twelve. Setting an amount per head means the deposit tracks the exposure automatically — the caller says eight, and the figure follows.'],
      },
      {
        heading: 'Picking the number',
        bullets: [
          { title: 'Enough to be remembered', body: 'The deposit works by making the booking real in somebody’s mind, not by covering your loss.' },
          { title: 'Not enough to lose the booking', body: 'If it reads as a charge rather than a hold, some groups will ring somewhere that does not ask.' },
          { title: 'Redeemable against the bill', body: 'It stops feeling like a fee the moment it comes off what they owe.' },
          { title: 'The same for everyone', body: 'Asking only the groups you are unsure about is a conversation nobody wants to have.' },
        ],
      },
      {
        heading: 'Taken during the call, not after',
        paras: ['A payment link sent afterwards gets opened by the one person who made the booking, some of the time. Handled while they are still on the phone and committed, it lands far more often — and the card details are entered by the caller on a payment page rather than read aloud to anybody.'],
      },
      {
        heading: 'When not to ask',
        paras: ['If your groups are mostly regulars who always turn up, a deposit buys you nothing and costs you goodwill. This is a tool for businesses losing real money to empty tables, not a default setting.'],
      },
    ],
    faqs: [
      { q: 'Can it take a deposit for a group booking?', a: 'Yes, and it can scale with party size — set an amount per head and the total follows the number the caller gives.' },
      { q: 'Why per person rather than a flat amount?', a: 'A flat deposit is a sensible hold on a table for two and a rounding error on a table for twelve. Per head, the deposit tracks what you actually stand to lose.' },
      { q: 'Are card details read out over the phone?', a: 'No. The caller enters them on a payment page; nothing sensitive is spoken aloud or stored in the call.' },
      { q: 'Will asking for a deposit cost me bookings?', a: 'Some, if the amount reads as a charge rather than a hold. Keep it modest and redeemable against the bill.' },
      { q: 'Should every business do this?', a: 'No. If your groups are regulars who turn up, a deposit buys nothing and costs goodwill.' },
    ],
    related: [
      { href: '/learn/reduce-no-shows-with-deposits', label: 'Deposits and no-shows', sub: 'Why they work at all.' },
      { href: '/learn/ai-receptionist-book-appointments', label: 'How booking works', sub: 'Live availability.' },
      { href: '/learn/cancellations-and-rescheduling-by-phone', label: 'Cancellations', sub: 'The other half.' },
    ],
    ctaHeading: 'Protect the bookings that cost most to lose.',
    ctaSub: 'Per-person deposits, taken on the call. Seven days free.',
  },
  {
    slug: 'spam-and-nuisance-calls',
    category: 'Common problem',
    shortTitle: 'Spam and junk calls',
    metaTitle: 'Spam, Robocalls and Nuisance Calls — Open Lines',
    metaDescription: 'What actually happens to telemarketers and wrong numbers, why nobody can truly block them, and the real benefit — junk calls stop distorting your numbers.',
    h1: 'What happens to spam and nuisance calls',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'Every business number attracts the same traffic: the energy broker, the SEO agency, the survey, the wrong number asking for a takeaway. It is a tax on having a phone, and the honest answer about it is less dramatic than most software promises.',
    sections: [
      {
        heading: 'The honest limitation first',
        paras: ['Nothing can reliably stop these calls arriving. Spoofed numbers change constantly, blocklists are always behind, and anything aggressive enough to catch most junk will eventually reject a customer — which is a far worse outcome than a wasted thirty seconds. Any product claiming to eliminate nuisance calls is either wrong or is silently doing that to you.'],
      },
      {
        heading: 'What actually changes',
        bullets: [
          { title: 'They stop interrupting you', body: 'The call is answered by something whose time is not scarce. You find out it was a broker by not being told.' },
          { title: 'They are identified as junk', body: 'Telemarketers, surveys, tests and wrong numbers are classified as what they are rather than filed as enquiries.' },
          { title: 'Your numbers stay honest', body: 'This is the real benefit. Counting a robocall as a missed opportunity drags your conversion rate down and makes every figure above it meaningless.' },
          { title: 'You are not notified', body: 'No alert, no summary demanding attention. Junk should cost you nothing, including the second it takes to dismiss a notification.' },
        ],
      },
      {
        heading: 'Why a wrong number is not spam',
        paras: ['Someone who dialled a digit wrong is a person, and should be told plainly they have the wrong place rather than interrogated by a booking flow. It is a small thing that says a lot about how a business handles people, including the ones who are not customers.'],
      },
      {
        heading: 'What still needs you',
        paras: ['If a specific number is harassing you, that is a matter for your telephone provider or, past a point, the police — not a software setting. And a supplier you genuinely deal with ringing about an invoice is not junk, however unwelcome; it should reach you like any other real call.'],
      },
    ],
    faqs: [
      { q: 'Can it block spam and robocalls?', a: 'Not reliably, and be suspicious of anything that claims otherwise. Spoofed numbers change constantly, and filters aggressive enough to catch most junk eventually reject real customers.' },
      { q: 'So what does it actually do?', a: 'It answers them so they do not interrupt you, identifies them as junk rather than enquiries, and keeps them out of your figures.' },
      { q: 'Why does that matter?', a: 'Because counting a telemarketer as a lost lead drags your conversion rate down and makes every number above it fiction.' },
      { q: 'Will I be notified about them?', a: 'No. Junk should cost you nothing, including the moment it takes to dismiss an alert.' },
      { q: 'What about a genuine wrong number?', a: 'That is a person, not spam. They should be told plainly they have the wrong place rather than pushed through a booking flow.' },
    ],
    related: [
      { href: '/learn/what-your-calls-are-telling-you', label: 'Insights from calls', sub: 'Why exclusions matter.' },
      { href: '/learn/urgent-calls-and-emergencies', label: 'Calls that need you', sub: 'The opposite problem.' },
      { href: '/learn/where-should-call-alerts-go', label: 'Where alerts go', sub: 'Being told the right things.' },
    ],
    ctaHeading: 'Let the brokers talk to something that does not mind.',
    ctaSub: 'Junk answered, classified, and kept out of your numbers. Seven days free.',
  },
  {
    slug: 'ai-receptionist-for-canadian-businesses',
    category: 'Guide',
    shortTitle: 'Canada',
    metaTitle: 'AI Receptionist for Canadian Businesses — Open Lines',
    metaDescription: 'Canadian numbers, PIPEDA and call recording consent, GST and HST on your bill, and an honest note for Quebec businesses serving French-speaking customers.',
    h1: 'AI receptionists for Canadian businesses',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'Canada is the straightforward end of this: numbers are issued without the business-verification step Ireland requires, and setup is a same-day job. There are three things worth knowing before you start, and one of them may rule us out for you.',
    sections: [
      {
        heading: 'Getting a number',
        paras: ['Local numbers are available across the country and there is no documentary verification to clear, so you are answering calls the day you sign up rather than waiting on a review. If you already have a business number, forward it — customers keep dialling what is on your van, your window and every listing you have ever created, and none of those update.'],
      },
      {
        heading: 'Consent, under PIPEDA',
        paras: ['Federal privacy law rests on meaningful consent, which in practice means callers should be told what is happening at the start rather than in terms nobody reads. Two things get disclosed: that the call is handled by an automated assistant, and that it is recorded or transcribed. Both belong in the opening seconds, before anyone has said anything they would not have said knowingly.'],
      },
      {
        heading: 'Provincial law does not disappear',
        paras: ['Alberta, British Columbia and Quebec each have their own private-sector privacy legislation, and Quebec’s has been the most active in recent years. For a small business answering its own phone the practical obligations converge — tell people, keep what you collect proportionate, and be able to delete it on request — but the details are worth a conversation with someone qualified if you handle anything sensitive.'],
      },
      {
        heading: 'GST and HST on your subscription',
        paras: ['Canadian sales tax is applied to your bill at the rate for your province, so what you pay differs between Ontario and Alberta. It appears as a line on the invoice rather than a surprise, and if you are registered it is recoverable in the ordinary way.'],
      },
      {
        heading: 'If your callers speak French',
        paras: ['Be aware that the assistant handles calls in English. For a business in Quebec — or anywhere with a substantial francophone customer base — that is a real limitation rather than a detail, and depending on your obligations and your customers it may be reason enough to choose something else. We would rather say so here than have you discover it on a Tuesday afternoon.'],
      },
    ],
    faqs: [
      { q: 'Do Canadian numbers need business verification?', a: 'No. Unlike Ireland there is no documentary review, so you can be answering calls the same day.' },
      { q: 'Is call recording legal in Canada?', a: 'With appropriate consent, yes. PIPEDA rests on meaningful consent, which means telling callers at the start of the call — both that it is an automated assistant and that it is recorded or transcribed.' },
      { q: 'Does provincial privacy law apply too?', a: 'Alberta, British Columbia and Quebec have their own private-sector legislation. For a small business the practical obligations converge, but anything sensitive is worth professional advice.' },
      { q: 'Will I be charged GST or HST?', a: 'Yes, at your province’s rate, shown as a line on the invoice. If you are registered it is recoverable as usual.' },
      { q: 'Does it speak French?', a: 'No — calls are handled in English. For a Quebec business or one with substantial francophone customers, that may be reason to choose a different product.' },
    ],
    related: [
      { href: '/learn/call-recording-consent', label: 'Recording consent', sub: 'What to say, and when.' },
      { href: '/learn/disclosing-ai-to-callers', label: 'Disclosing the AI', sub: 'The other disclosure.' },
      { href: '/learn/keep-your-business-phone-number', label: 'Keeping your number', sub: 'Forward, do not replace.' },
    ],
    ctaHeading: 'Answering Canadian calls today, not next week.',
    ctaSub: 'No verification queue, local numbers, tax handled on the invoice. Seven days free.',
  },
  {
    slug: 'taking-pressure-off-a-busy-front-desk',
    category: 'Common problem',
    shortTitle: 'Busy front desk',
    metaTitle: 'Taking Pressure Off a Busy Front Desk — Open Lines',
    metaDescription: 'When one person is serving a customer, taking a payment and answering a ringing phone, something gets dropped. Which calls to hand over and which to keep.',
    h1: 'Taking pressure off a busy front desk',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'You have someone on the desk, so the phone is covered — until eleven on a Saturday, when there are four people waiting, a card machine thinking about it, and a phone that has rung nine times. Having a receptionist and having the phone answered are not the same thing at the moments that matter.',
    sections: [
      {
        heading: 'The cost is paid by the person in front of you',
        paras: ['A desk answering the phone mid-transaction is not doing either job properly. The customer standing there watches themselves become less important than someone who is not in the room, and your receptionist spends the day being interrupted out of every task they start. Both of those are real costs that never appear anywhere you can see them.'],
      },
      {
        heading: 'Hand over the repetition, keep the judgment',
        bullets: [
          { title: 'Hand over: hours, prices, parking, directions', body: 'Fixed answers that never vary. This is the bulk of the volume and none of the skill.' },
          { title: 'Hand over: routine availability and booking', body: 'The two-minute call that interrupts a ten-minute task.' },
          { title: 'Keep: the person at the counter', body: 'Always. They came in.' },
          { title: 'Keep: complaints and complicated exceptions', body: 'Anything needing discretion should reach a human quickly and unmistakably.' },
        ],
      },
      {
        heading: 'Overflow rather than replacement',
        paras: ['The version that works is not switching the desk off. It is that calls arriving when the desk is genuinely occupied get answered instead of ringing out, which is a narrower change than replacing anybody and produces most of the benefit. Your receptionist keeps the calls they are good at and stops being interrupted during the ones they are not needed for.'],
      },
      {
        heading: 'How to tell if this is your problem',
        paras: ['Watch your desk between eleven and one on your busiest day. Count how many times the phone rings while somebody is mid-conversation with a customer, and how many of those rings the caller waits out. That number is the size of the problem, and most owners are surprised by it because they are not usually standing there.'],
      },
    ],
    faqs: [
      { q: 'I already have a receptionist — is this useful?', a: 'It is, as overflow rather than replacement. Having a desk and having the phone answered are different things at eleven on a Saturday.' },
      { q: 'Which calls should the desk keep?', a: 'The customer standing in front of them, complaints, and anything needing discretion. Hand over hours, prices, directions and routine bookings.' },
      { q: 'Does it replace the person?', a: 'No, and the version that works does not try. It answers what arrives while the desk is genuinely occupied.' },
      { q: 'How do I know if I have this problem?', a: 'Stand at your desk between eleven and one on your busiest day and count the rings that land mid-conversation. Most owners are surprised, because they are not usually there.' },
    ],
    related: [
      { href: '/learn/stop-missing-calls-while-with-a-customer', label: 'Calls missed while busy', sub: 'The same hour, closer up.' },
      { href: '/learn/handling-busy-periods-and-call-spikes', label: 'Call spikes', sub: 'When everything lands at once.' },
      { href: '/learn/covering-the-phone-during-staff-holidays', label: 'Holiday cover', sub: 'When the desk is empty.' },
    ],
    ctaHeading: 'Stop making the customer in front of you wait.',
    ctaSub: 'Overflow answered, desk uninterrupted. Seven days free.',
  },
  {
    slug: 'stop-losing-callers-to-the-next-business',
    category: 'Common problem',
    shortTitle: 'Losing callers to rivals',
    metaTitle: 'Why Callers Ring Your Competitor Next — Open Lines',
    metaDescription: 'People searching for a service ring two or three numbers in a row. Why answering first matters more than being better, and what the caller is actually deciding.',
    h1: 'Why callers ring your competitor next',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'Somebody searches for what you do, opens three results, and starts dialling. They are not comparing you carefully — they are working down a list until somebody picks up. This is the least romantic fact about winning work on the phone and one of the most consequential.',
    sections: [
      {
        heading: 'What they are actually deciding',
        paras: ['Not who is best. At the moment of dialling they have already decided everyone on the list is probably fine, and they are now resolving a much smaller question: who can deal with this today. Answering is not a courtesy in that context; it is the entire basis on which they are choosing, and the second name on the list gets the work by being available.'],
      },
      {
        heading: 'Why your reviews do not save you',
        paras: ['A four-point-nine average gets you onto the list. It does not survive an unanswered phone, because the caller does not conclude you are bad — they conclude you are busy, which is a compliment that costs you the job. Ratings determine who gets dialled; answering determines who gets booked.'],
      },
      {
        heading: 'Where the losses concentrate',
        bullets: [
          { title: 'The first hour of the working day', body: 'People ring about problems they slept on. The business that answers at eight has usually taken the job before the one that opens at nine is unlocking.' },
          { title: 'Lunchtime', body: 'Callers ring on their own break, which is precisely your break.' },
          { title: 'Early evening', body: 'The other window people have free — and one most trades and salons are travelling through.' },
          { title: 'Any hour you are with a customer', body: 'Which is, ideally, most of them.' },
        ],
      },
      {
        heading: 'What "answered" has to mean',
        paras: ['Picking up is necessary and not sufficient. A caller who reaches a hold queue, or a voice that takes a message for somebody to deal with tomorrow, is still shopping — they have not got what they rang for. Answered means they leave the call with the thing they wanted: a time, a price, or a clear next step with a name on it.'],
      },
    ],
    faqs: [
      { q: 'Do people really ring more than one business?', a: 'Routinely. Someone searching for a service opens several results and works down the list until somebody picks up — most decisions are made before the second name has finished ringing.' },
      { q: 'Won’t good reviews make them wait for me?', a: 'Reviews get you onto the list; they do not survive an unanswered phone. The caller does not decide you are bad, only that you are busy — which costs you the job just the same.' },
      { q: 'When do I lose the most work?', a: 'The first hour of the day, lunchtime, early evening, and any hour you are with a customer.' },
      { q: 'Is picking up enough?', a: 'No. A hold queue or a message to be dealt with tomorrow leaves them still shopping. They need to leave the call with a time, a price, or a clear next step.' },
    ],
    related: [
      { href: '/learn/is-an-ai-receptionist-worth-it', label: 'The arithmetic', sub: 'What a lost caller costs.' },
      { href: '/learn/ai-receptionist-after-hours', label: 'After-hours calls', sub: 'The windows you are closed.' },
      { href: '/learn/qualifying-leads-on-the-phone', label: 'Qualifying enquiries', sub: 'Once you have answered.' },
    ],
    ctaHeading: 'Be the one that picks up.',
    ctaSub: 'Because that is what they are actually deciding. Seven days free.',
  },
  {
    slug: 'hidden-costs-of-a-cheap-answering-service',
    category: 'Cost guide',
    shortTitle: 'Cheap answering services',
    metaTitle: 'The Hidden Costs of a Cheap Answering Service — Open Lines',
    metaDescription: 'Per-call pricing, minimum charges, junk you pay to have answered, and the cost nobody itemises: a message is not a booking, so the work still lands on you.',
    h1: 'The hidden costs of a cheap answering service',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'The headline price on an answering service is rarely the price. That is not usually dishonesty — it is that the cheap tiers are priced per call, and neither you nor they know how many calls you will get or what will be on them.',
    sections: [
      {
        heading: 'What the invoice actually contains',
        bullets: [
          { title: 'Calls you would not have wanted', body: 'Telemarketers and wrong numbers are answered, and on per-call pricing you pay for each one. You are buying the privilege of having a broker greeted politely.' },
          { title: 'Rounding', body: 'A forty-second call billed as a minute is a fifty per cent premium on your most common call.' },
          { title: 'Minimum monthly commitments', body: 'Quiet months cost the same as busy ones, which removes the flexibility the per-call model appeared to offer.' },
          { title: 'Out-of-hours surcharges', body: 'Evenings and weekends — the hours you most wanted covering — often carry a different rate.' },
        ],
      },
      {
        heading: 'The cost that never appears on the bill',
        paras: ['A message is not a booking. Every call handled as a message becomes a task for you: read it, ring back, hope they answer, find the slot, take the details. You have paid to be told about the call and then done the work anyway — and in the gap between the message and your callback, some of those people have booked somewhere else.'],
      },
      {
        heading: 'The second one, also invisible',
        paras: ['Whoever answers does not know your business. They cannot say what a treatment costs, whether you cover a postcode, or how long a job usually takes — so callers with simple questions get a promise that somebody will ring them back. Those were the easiest calls you had, converted into callbacks.'],
      },
      {
        heading: 'How to compare them honestly',
        paras: ['Ignore the monthly figure entirely and work out cost per completed outcome — a booking made, or a question genuinely answered. A cheap service that turns eighty per cent of calls into callbacks is not cheap; it is a queue you pay for. Ask any provider what proportion of calls end without further work for you, and take the vagueness of the answer as information.'],
      },
    ],
    faqs: [
      { q: 'Why is my answering service bill higher than the quoted price?', a: 'Usually per-call pricing, rounding short calls up to a minute, minimum monthly commitments, and out-of-hours surcharges on exactly the hours you wanted covered.' },
      { q: 'Do I pay for spam calls?', a: 'On per-call pricing, generally yes — you are paying for a telemarketer to be greeted politely.' },
      { q: 'What is the biggest cost that is not on the invoice?', a: 'That a message is not a booking. You pay to be told about the call and then do the work anyway, and some of those callers book elsewhere in the meantime.' },
      { q: 'How should I compare providers?', a: 'On cost per completed outcome — a booking made or a question actually answered — not monthly price. Ask what share of calls end with no further work for you.' },
    ],
    related: [
      { href: '/learn/answering-service-cost', label: 'What they cost', sub: 'The pricing models.' },
      { href: '/learn/switching-from-an-answering-service', label: 'Switching over', sub: 'How to move.' },
      { href: '/learn/cost-per-booked-appointment', label: 'Cost per booking', sub: 'The comparison that settles it.' },
    ],
    ctaHeading: 'Compare on outcomes, not on price.',
    ctaSub: 'Bookings made, not messages taken. Seven days free.',
  },
  {
    slug: 'how-long-does-setup-actually-take',
    category: 'Guide',
    shortTitle: 'How long setup takes',
    metaTitle: 'How Long Does It Take to Set Up? — Open Lines',
    metaDescription: 'Twenty minutes for most businesses, longer in Ireland, and an honest account of what takes the time — plus the four things worth doing before you start.',
    h1: 'How long does it actually take to set up?',
    published: '2026-09-15',
    updated: '2026-09-15',
    intro: 'For most businesses, under half an hour from signing up to a working number — because the slow part, teaching it about your business, is done by reading your website rather than by you filling in forms. There are two situations where it takes meaningfully longer, and both are worth knowing about in advance.',
    sections: [
      {
        heading: 'Where the time goes',
        bullets: [
          { title: 'Reading your website: a couple of minutes', body: 'Services, prices and hours are pulled from your existing site while you carry on with the rest of setup.' },
          { title: 'Getting a number: immediate in most countries', body: 'Available straight away in Canada, the US and the UK.' },
          { title: 'Connecting your calendar: about five minutes', body: 'A sign-in and an approval. This is the step worth not skipping.' },
          { title: 'Checking it: ten minutes', body: 'Ring your own number and ask the three things customers ask most. This is the only part that genuinely needs you.' },
        ],
      },
      {
        heading: 'The exception: Ireland',
        paras: ['Irish numbers require business verification before they can be issued — documents submitted and reviewed, which takes days rather than minutes. Everything else can be set up while that runs, so the wait is on the number alone rather than on the whole arrangement. It is a regulatory requirement, not a queue anyone controls.'],
      },
      {
        heading: 'The other exception: a thin website',
        paras: ['If your site is one page with a contact form, there is little to learn from and the assistant will start with gaps. That is not a longer setup so much as an extra twenty minutes writing down your ten most-asked questions and uploading them — which is worth doing regardless, and pays back faster than anything else you could spend that time on.'],
      },
      {
        heading: 'Four things to have ready',
        paras: ['Your website address, access to your calendar account, your current opening hours including anything seasonal, and a rough answer to your most awkward pricing question. With those to hand it is a single sitting; without them it becomes two.'],
      },
    ],
    faqs: [
      { q: 'How long does setup take?', a: 'Under half an hour for most businesses. The slow part — learning your services, prices and hours — is done by reading your website rather than by you filling in forms.' },
      { q: 'Why does Ireland take longer?', a: 'Irish numbers require business verification before they can be issued, which takes days. Everything else can be set up while that runs.' },
      { q: 'What if my website is very basic?', a: 'Allow an extra twenty minutes to write down your ten most-asked questions and upload them. Worth doing regardless of your website.' },
      { q: 'What should I have ready?', a: 'Your website address, access to your calendar account, your opening hours including seasonal ones, and an answer to your most awkward pricing question.' },
      { q: 'Do I need technical help?', a: 'No. The only steps are signing in to your calendar and ringing your own number to check it.' },
    ],
    related: [
      { href: '/learn/your-first-week-with-an-ai-receptionist', label: 'Your first week', sub: 'What to check, day by day.' },
      { href: '/learn/irish-business-phone-number', label: 'Irish verification', sub: 'What the wait involves.' },
      { href: '/learn/how-an-ai-receptionist-learns-your-business', label: 'How it learns', sub: 'Where the answers come from.' },
    ],
    ctaHeading: 'Twenty minutes, one sitting.',
    ctaSub: 'Website read, calendar connected, number live. Seven days free.',
  },
]

export const ARTICLE_SLUGS = ARTICLES.map(a => a.slug)

export function getArticle(slug: string): LearnArticle | undefined {
  return ARTICLES.find(a => a.slug === slug)
}
