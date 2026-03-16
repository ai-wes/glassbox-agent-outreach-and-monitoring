from __future__ import annotations

import asyncio
import csv
import io
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("GTM_DATABASE_URL", f"sqlite+aiosqlite:///{ROOT / 'data' / 'gtm.db'}")

from outreach_app.gtm_service.core.config import get_settings
from outreach_app.gtm_service.db.models import Company, Contact, Lead, LeadScore, LeadStatus, Signal
from outreach_app.gtm_service.db.session import AsyncSessionLocal, init_db
from outreach_app.gtm_service.services.crm import SheetsCRMService
from outreach_app.gtm_service.services.metrics import MetricsService


FIRM_CSV = """priority_score,priority_bucket,firm,firm_type,why_relevant_for_glassbox,public_signal,best_entry_route,official_url,last_verified
5,Tier 1,ARCH Venture Partners,venture fund / company creation,Historically one of the strongest firms for company creation around ambitious biology platforms and enabling technologies.,ARCH profiles repeatedly emphasize disruptive platform technologies and biotech company creation.,"Warm intro from scientist-founder, academic spinout network, or respected co-investor.",https://www.archventure.com/,2026-03-08
5,Tier 1,Andreessen Horowitz (a16z) Bio + Health,venture fund,"Large, active bio platform investor with explicit interest in therapeutic platforms, life-sciences software, and enabling datasets.",a16z launched the Biotech Ecosystem Venture Fund with Lilly in 2025 for therapeutic platforms and cutting-edge tech companies.,"Warm intro from founder, scientist, or pharma operator; concise evidence-driven memo.",https://a16z.com/bio-health/,2026-03-08
5,Tier 1,DCVC Bio,venture fund,Deep-tech biology investor explicitly interested in founders combining biology and deep compute; strongest fit for verification and reproducibility infrastructure.,DCVC Bio says it seeks founders marrying deep biological insights and/or engineering with deep compute; Bio III closed at $400M in 2024.,"Warm intro from scientist-founder, operator, or syndicate investor; founder-submission angle can work if highly technical.",https://www.dcvc.com/bio,2026-03-08
5,Tier 1,Flagship Pioneering,venture studio / platform company creator,Most relevant if Glassbox is pitched as a true platform company or company-creation opportunity around AI-native scientific verification.,Flagship formalized Pioneering Intelligence and continues launching AI-native platform companies such as Lila Sciences and Expedition Medicines.,"Origination conversation through scientific, founder, or operator network; platform narrative required.",https://www.flagshippioneering.com/,2026-03-08
5,Tier 1,GV,venture fund,"Strong life-sciences bench with multiple partners who have machine learning, computational biology, and company-formation backgrounds.",GV’s life-sciences team includes ML/statistical genetics and computational biology expertise plus company incubation history.,"Warm intro through founders, academics, or syndicate investors; technical memo and clear wedge matter.",https://www.gv.com/,2026-03-08
5,Tier 1,Lux Capital,venture fund,Contrarian deep-science investor that often funds category-defining infrastructure before it is obvious.,Lux announced Fund IX in January 2026 and continues to highlight frontier science and healthcare bets.,Warm intro or sharp cold email with a clear technical breakthrough and category insight.,https://www.luxcapital.com/,2026-03-08
4,Tier 2,Khosla Ventures,venture fund,"Strong fit if you can sell Glassbox as a large market control point at the intersection of biotech, healthcare, data science, and AI.","Relevant Khosla partners publicly list biotechnology, healthcare, data science, and AI/ML as core focus areas.",Warm intro or concise contrarian outbound with category-scale framing.,https://khoslaventures.com/,2026-03-08
4,Tier 2,Obvious Ventures,venture fund,Growing generative-science thesis; useful if Glassbox is framed as enabling trustworthy AI in science rather than pure wet-lab tooling.,Obvious announced OV5 in January 2026 and publicly highlighted generative science and human-health themes.,Warm intro tied directly to the firm’s generative science / human health thesis.,https://obvious.com/,2026-03-08
4,Tier 2,SOSV SF / SOSV NY (formerly IndieBio),accelerator / venture fund,"Best fit if still early and you want lab infrastructure, fast founder feedback loops, and structured investor access.","SOSV’s bio program offers up to $550K pre-seed SAFE, demo days, and a 7,000+ investor network. Current March 2026 branding is SOSV SF / SOSV NY, though program pages remain on indiebio.co.",Apply directly through the program and use demo days and matchups for follow-on VC access.,https://indiebio.co/program/,2026-03-08
3,Tier 3,S32,venture fund,"Useful secondary target for frontier-tech framing, but less directly targeted than the top bio/deep-tech firms above.",S32 publicly describes itself as investing at the frontiers of technology; market coverage also places it in computational biology and precision medicine.,Strong network intro from technical founders or life-science operators.,https://www.s32.com/,2026-03-08
"""


PERSON_CSV = """priority_score,priority_bucket,firm,person,title,firm_type,stage_fit,public_focus,selected_public_examples,firm_signal,why_fit_for_glassbox,suggested_pitch_angle,intro_path_recommendation,cold_outbound_viability,official_profile_url,official_firm_url,last_verified,crm_status,next_step,internal_notes
5,Tier 1,ARCH Venture Partners,Kristina Burow,Managing Director,venture fund / company creation,Seed-A / company creation,"Focused on the creation and development of biotechnology, pharmaceutical, and health tech companies.",Orbital Therapeutics; Boundless Bio; ROME Therapeutics; Pretzel Therapeutics; Beam Therapeutics; Metsera,Kristina’s public profile is directly about company creation and development in biotech and health tech.,Strong fit for a platform story with both biotech and health-tech infrastructure implications.,"Verification infrastructure is becoming a company category, not a feature; Glassbox can underwrite better science and better businesses.","Warm intro via founders, operators, or Boston/San Diego biotech networks is ideal.",Low-Medium,https://www.archventure.com/team/kristina-burow/,https://www.archventure.com/,2026-03-08,,,
5,Tier 1,ARCH Venture Partners,Nilay Thakar,Principal,venture fund / company creation,Seed-A,"Focuses on company creation, identifying and evaluating new life-science technologies, and helping early-stage portfolio companies; includes life-science tools.",Arbor Biotechnologies; hC Bioscience; OneBioMed; Skylark Bio,"Nilay’s profile explicitly includes life-science tools and early-stage company creation, which is unusually relevant for Glassbox.",Excellent practical fit for a life-science tools / infrastructure wedge into broader platform company potential.,Start as a life-science tools company with platform upside; show early adoption path and long-term strategic leverage.,Warm intro through early-stage tool founders or ARCH-connected operators.,Medium,https://www.archventure.com/team/nilay-thakar/,https://www.archventure.com/,2026-03-08,,,
5,Tier 1,ARCH Venture Partners,Robert Nelsen,Co-founder & Managing Director,venture fund / company creation,Seed-A / company creation,Focused on disruptive technologies and novel platform technologies; helped create and develop more than 150 companies.,Illumina; Beam Therapeutics; GRAIL; insitro; Xaira Therapeutics; Prime Medicine; Maze Therapeutics; Verve Therapeutics,ARCH continues to back and create biology platform companies with large technical ambition and long time horizons.,One of the best fits if Glassbox is truly category-level platform infrastructure for AI biology and not just a tool point-solution.,Pitch Glassbox as a novel platform technology that improves every downstream AI-biology company ARCH might back.,"Warm intro through scientists, founders, syndicate investors, or major academic spinout ecosystem.",Low-Medium,https://www.archventure.com/team/robert-nelsen/,https://www.archventure.com/,2026-03-08,,,
5,Tier 1,Andreessen Horowitz (a16z) Bio + Health,Ben Portney,Investing Partner,venture fund,Seed-A,Investing partner focused on early-stage companies building platforms for novel therapeutic discovery and development.,Orbital Therapeutics; insitro; BigHat Biosciences; Rezo Therapeutics; Octant Bio,Ben’s public profile is directly aligned to early-stage platform companies rather than single-asset biotech stories.,One of the cleanest direct fits for an early-stage validation platform that strengthens novel therapeutic discovery programs.,Show how Glassbox becomes core infrastructure for model-to-experiment loops in early platform companies.,Warm intro from an early-stage techbio founder or angel; technical memo beats polished marketing here.,Medium,https://a16z.com/author/ben-portney/,https://a16z.com/bio-health/,2026-03-08,,,
5,Tier 1,Andreessen Horowitz (a16z) Bio + Health,Jorge Conde,General Partner,venture fund,Seed-A-B,"Invests across therapeutics, diagnostics, tools, and software at the intersection of biology, computer science, and engineering.",Asimov; Cartography; Dyno; Octant Bio,"a16z Bio + Health continues to publish around bio platforms and platform-disease fit, and the Lilly partnership reinforces its interest in enduring therapeutic platforms.",Very strong fit for a biology x compute infrastructure story that removes validation friction from AI-generated hypotheses and assays.,Position Glassbox as the missing 'platform-confidence' layer between model output and experimental decision-making.,"Warm intro from a bio founder, scientific advisor, or operator is best; include a concrete workflow where Glassbox prevented or would prevent false confidence.",Low-Medium,https://a16z.com/author/jorge-conde/,https://a16z.com/bio-health/,2026-03-08,,,
5,Tier 1,Andreessen Horowitz (a16z) Bio + Health,Vineeta Agarwala,General Partner,venture fund,Seed-A-B,"Leads investments across biotech, life sciences software, and digital health, especially companies leveraging unique technologies and datasets to advance drug development and personalized medicine.",,a16z announced the Biotech Ecosystem Venture Fund with Lilly in 2025 to invest in therapeutic platforms and cutting-edge technology companies.,"Strong fit if Glassbox is framed as the trust, validation, and data-governance layer for AI-native drug discovery and platform biology.","AI-designed biology needs an independent verification layer before assets become partnerable; Glassbox makes experimental outputs reproducible, auditable, and investable.","Best via warm intro from founder, scientist, angel, or pharma operator; send a short memo with one killer benchmark or pilot result.",Low-Medium,https://a16z.com/author/vineeta-agarwala/,https://a16z.com/bio-health/,2026-03-08,,,
5,Tier 1,DCVC Bio,John Hamer,"Managing Partner, DCVC Bio",venture fund,Seed-A-B,"Co-founded DCVC Bio and backs foundational deep-tech life-science initiatives across human health, agriculture, and synthetic biology.",AbCellera; Creyon Bio; Umoja Biopharma,DCVC Bio explicitly seeks founders marrying deep biological insight or engineering with deep compute; DCVC Bio III closed at $400M in 2024.,Top-tier fit for a platform removing a foundational bottleneck in techbio rather than building a single therapeutic asset.,Glassbox is a deep-tech life-science platform that upgrades the reliability of AI-biological discovery across many downstream programs.,"Warm intro from scientist-founder, operator, or existing DCVC-friendly syndicate is ideal; lead with the hard problem and why software alone does not solve it.",Medium,https://www.dcvc.com/team/john-hamer,https://www.dcvc.com/bio,2026-03-08,,,
5,Tier 1,DCVC Bio,Justin Kern,"Partner, DCVC Bio",venture fund,Seed-A,"Identifies companies using technology to solve problems across therapeutics, agriculture, food, and industrial applications.",,Justin’s profile highlights company-building support from foundation through exit and a broad technology-plus-biology lens.,Good fit for a foundational platform that can land in therapeutics first and expand across broader biology workflows later.,Start with therapeutic discovery QA and show the broader platform surface area that follows.,"Warm intro from a scientist, CRO operator, or portfolio founder; emphasize expansion path and technical moat.",Medium,https://www.dcvc.com/team/dr-justin-kern,https://www.dcvc.com/bio,2026-03-08,,,
5,Tier 1,DCVC Bio,Kiersten Stead,"Managing Partner, DCVC Bio",venture fund,Seed-A-B,"Scientist-investor focused on deep-tech platforms in therapeutics, agriculture and food, and industrial biotechnology.",Creyon Bio; Umoja; Latus Bio; Grove Biopharma,DCVC Bio publicly emphasizes biology plus frontier compute and founder submissions for companies marrying biology and deep compute.,"Excellent fit for a reproducibility and verification platform that cuts across therapeutic, synthetic biology, and data-driven experimental workflows.","Lead with Glassbox as a cross-portfolio platform: less false confidence, cleaner data loops, better translational readiness.",Warm scientific intro preferred; concise technical narrative with evidence of customer urgency will travel well.,Medium,https://www.dcvc.com/team/kiersten-stead,https://www.dcvc.com/bio,2026-03-08,,,
5,Tier 1,Flagship Pioneering,Geoffrey von Maltzahn,General Partner,venture studio / platform company creator,Company creation / Seed,Inventor and entrepreneur who co-founded multiple companies integrating biology and data science to transform human health and sustainability.,Lila Sciences; Quotient Therapeutics; Mirai Bio; Tessera Therapeutics; Generate:Biomedicines; Indigo; Sana,"Flagship has formalized Pioneering Intelligence and keeps launching AI-native platform companies, including Lila Sciences and Expedition Medicines.",Potentially one of the most strategic long-range fits if Glassbox is conceived as a true platform company rather than a standalone tooling feature.,Pitch Glassbox as a company capable of becoming default verification infrastructure for AI-led science and autonomous lab systems.,"Best via origination/venture-creation network, scientific advisor, or operator intro; platform concept is essential.",Low,https://www.flagshippioneering.com/people/geoffrey-von-maltzahn,https://www.flagshippioneering.com/,2026-03-08,,,
5,Tier 1,Flagship Pioneering,Molly Gibson,Origination Partner,venture studio / platform company creator,Company creation / Seed,Leads founding and growth of companies at the intersection of AI and science.,Lila Sciences; Generate: Biomedicines; Tessera Therapeutics; Expedition Medicines,"Molly’s current remit is exactly AI x science company origination, making her highly relevant for a new platform category.",Excellent fit if Glassbox is positioned as foundational infrastructure for AI running the scientific method and needing trustworthy feedback loops.,Glassbox is the evidence-and-verification substrate that lets AI-native labs operate safely and credibly at scale.,"Best through top scientific operators, founders, or mutual investors; the deck should read like a platform origination thesis, not SaaS positioning.",Low-Medium,https://www.flagshippioneering.com/people/molly-gibson,https://www.flagshippioneering.com/,2026-03-08,,,
5,Tier 1,GV,Brendan Bulik-Sullivan,General Partner,venture fund,Seed-A-B,Life sciences investor with background in applied statistics and machine learning research in genetics and biotechnology.,Maze Therapeutics; Metsera; Santa Ana Bio; Ventus Therapeutics; Areteia Therapeutics,"GV’s life-sciences team includes investors with explicit ML, genetics, and early-stage platform backgrounds.",Very strong fit for an ML-native biology infrastructure story because Brendan understands both algorithms and wet-lab biotech realities.,"Position Glassbox as the layer that raises signal quality in model-training, candidate triage, and experimental interpretation.","Warm intro through Broad/ML-genetics/portfolio networks; come prepared with technical benchmarks, not just TAM language.",Medium,https://www.gv.com/team/brendan-bulik-sullivan,https://www.gv.com/,2026-03-08,,,
5,Tier 1,GV,Issi Rozen,General Partner,venture fund,Seed-A / company creation,Primarily focuses on company formation and early-stage life-science investments.,Aera Therapeutics; EveryONE Medicines; Mestag Therapeutics; Verve Therapeutics; nChroma Bio,Issi’s profile is explicitly oriented to formation and early-stage science rather than only later-stage de-risked biotech.,High fit for a platform company that may define a new category in AI-native scientific verification.,"Pitch Glassbox as a company-creation-grade platform that can underpin multiple products, workflows, or even spinout paths.",Warm intro from early-stage life-science founders or Broad ecosystem contacts is ideal.,Low-Medium,https://www.gv.com/team/issi-rozen,https://www.gv.com/,2026-03-08,,,
5,Tier 2,Khosla Ventures,Alex Morgan,Partner,venture fund,Seed-A-B,"Focuses on biotechnology, healthcare, data science, and AI/ML.",,Alex’s profile is one of the clearest public intersections of biotech and AI/ML among major venture investors.,"Very strong fit for a platform story centered on computation, biology, and clinical or translational impact.",Present Glassbox as the system that converts computational promise into trustworthy experimental and translational evidence.,"Warm intro preferred, but crisp contrarian outbound with technical proof may work.",Medium,https://khoslaventures.com/team/alex-morgan,https://khoslaventures.com/,2026-03-08,,,
5,Tier 1,Lux Capital,David Yang,Partner,venture fund,Seed-A,"Invests in life sciences across therapeutics, R&D tools, and biopharma infrastructure.",,"David’s public Lux profile is unusually direct about therapeutics, R&D tools, and biopharma infrastructure—high relevance for Glassbox.",Arguably the clearest current Lux fit for a research-infrastructure or validation-stack company.,"Frame Glassbox as biopharma infrastructure that improves lab trust, downstream BD readiness, and capital efficiency.","Try warm intro from Broad/Biotech tools/8VC/Bio infra network; if outbound, keep it practical and workflow-specific.",Medium-High,https://www.luxcapital.com/people/david-yang,https://www.luxcapital.com/,2026-03-08,,,
5,Tier 1,Lux Capital,Josh Wolfe,Partner and Co-Founder,venture fund,Seed-A-B,"Co-founded Lux; invests in defense, biotech, and company creation around hard science.",Aera Therapeutics; Eikon Therapeutics; Variant Bio; Kallyope; Resilience,Lux announced Fund IX in January 2026 and continues to emphasize frontier science and contrarian technical bets.,Excellent fit for a contrarian deep-science platform thesis: the new bottleneck is not model generation but trusted biological verification.,"Pitch Glassbox as the infrastructure that turns AI-bio enthusiasm into real, reproducible science and faster capital allocation.","Warm intro works best, but Lux will sometimes respond to sharp cold outbound if the technical insight is non-obvious and the proof is real.",Medium,https://www.luxcapital.com/people/josh-wolfe,https://www.luxcapital.com/,2026-03-08,,,
5,Tier 1,Lux Capital,Peter Hébert,Partner and Co-Founder,venture fund,Seed-A-B,Co-founded Lux and invests across ambitious science and healthcare ventures.,Auris Health; Matterport; Vium,Lux remains active across science-heavy sectors and supports once-impossible technical bets that can become core infrastructure or categories.,Good fit if Glassbox is positioned as scientific infrastructure that can become a system of record for experimental confidence in AI biology.,"Emphasize that validation and reproducibility are becoming category-defining infrastructure, not mere workflow tools.",Best via founder-to-founder or operator intro; show why the problem is inevitable and underappreciated.,Medium,https://www.luxcapital.com/people/peter-hebert,https://www.luxcapital.com/,2026-03-08,,,
5,Tier 2,Obvious Ventures,Rohan Ganesh,Partner,venture fund,Seed-A,Invests in mission-driven teams transforming pharma operations and catalyzing biological breakthroughs.,Ataraxis AI (publicly featured by Obvious),"Rohan’s profile language is highly aligned to biological breakthroughs and pharma operations, not just generic software.",Possibly the best Obvious fit for a science operations and validation platform.,Glassbox upgrades pharma and biotech operating systems by making AI-linked experiments explainable and reproducible.,Warm intro through Verily/Northpond/biotech founder network.,Medium,https://obvious.com/team/rohan-ganesh/,https://obvious.com/,2026-03-08,,,
4,Tier 1,ARCH Venture Partners,Steve Gillis,Managing Director,venture fund / company creation,Seed-A-B,Focused on the evaluation of new life-science technologies and on the development and growth of ARCH’s biotechnology portfolio companies.,beBio; Inograft; SonoThera; Dispatch Bio; eGenesis; Skylark Bio,Steve’s profile emphasizes evaluation of new life-science technologies rather than only late-stage de-risked biotech.,Useful for a deeply scientific story centered on evaluation quality and technical differentiation.,Lead with the scientific pain: bad validation decisions waste years of platform-company value creation.,Warm intro through biotech founders or scientific advisors.,Low,https://www.archventure.com/team/steve-gillis/,https://www.archventure.com/,2026-03-08,,,
4,Tier 1,Flagship Pioneering,Armen Mkrtchyan,Origination Partner,venture studio / platform company creator,Company creation / Seed,Leads a team to invent and launch breakthrough platform companies grounded in artificial intelligence.,,Armen is directly focused on new AI-grounded platform origination inside Flagship.,Strong fit if Glassbox is framed as an AI-era platform company rather than just biotech tooling.,"Lead with the architecture of a new AI-science control layer: provenance, verification, and decision confidence.",Warm intro or direct outreach with a one-page thesis memo can work better than a conventional fundraise deck.,Medium,https://www.flagshippioneering.com/people/armen-mkrtchyan,https://www.flagshippioneering.com/,2026-03-08,,,
4,Tier 1,Flagship Pioneering,Jacob Rubens,Origination Partner,venture studio / platform company creator,Company creation / Seed,Scientist entrepreneur leading company formation based on new biotechnology.,Quotient Therapeutics; Tessera Therapeutics; Sana Biotechnology; Kaleido Biosciences,Jake’s profile is squarely about founding and growing new biotech platforms from first principles.,Relevant if you want to pitch Glassbox as a platform that can spawn multiple product and workflow lines across bio R&D.,Emphasize new-biotechnology category creation and the ability to build multiple products on a core verification engine.,"Best through scientist-founder networks and company creators, not generic VC channels.",Low-Medium,https://www.flagshippioneering.com/people/jacob-rubens,https://www.flagshippioneering.com/,2026-03-08,,,
4,Tier 1,GV,Krishna Yeshwant,Managing Partner,venture fund,Seed-A-B,"Co-leads GV’s life sciences group and invests across therapeutics, diagnostics, care delivery, health IT, and company incubation.",Flatiron Health; Foundation Medicine; Relay Therapeutics; Beam Therapeutics; insitro; One Medical,Krishna helped establish GV’s incubation program and has a track record backing category-defining life-science companies.,Useful if Glassbox is framed broadly as category-defining infrastructure with relevance across therapeutics and data-centric care/diagnostics ecosystems.,Show platform breadth: verification that matters for therapeutics today and regulated biological decision systems more broadly over time.,Warm intro through top-tier founders or syndicate investors; focus on ambition and category creation.,Low-Medium,https://www.gv.com/team/krishna-yeshwant,https://www.gv.com/,2026-03-08,,,
4,Tier 1,GV,Sherry Chao,Partner,venture fund,Seed-A-B,Life sciences investor with computational biology training and cancer immunology research experience.,Merida Biosciences; Metsera; Santa Ana Bio,Sherry’s computational biology background makes her relevant for data-centric bio infrastructure.,"Good fit if Glassbox is framed as infrastructure for higher-quality biological data, evaluation, and decision support.",Emphasize how verification infrastructure compounds the value of proprietary datasets and AI pipelines.,Warm intro through biotech founders or Harvard/Broad-adjacent network; keep it technically crisp.,Medium,https://www.gv.com/team/sherry-chao,https://www.gv.com/,2026-03-08,,,
4,Tier 2,Khosla Ventures,Nessan Bermingham,Operating Partner,venture fund,Seed-A-B,"Focused on life-science companies emphasizing nucleic acid editing, novel delivery systems, gene and cell therapy, novel target identification, and data analytics for drug discovery and development.",Everyone Medicines; Korro Bio; Deep Genomics; Ochre Bio; Bionaut Labs,Nessan’s profile is unusually direct about data analytics for drug discovery and development.,"Strong fit for a pitch centered on better target-validation, analytics, and confidence in drug-discovery decision loops.",Glassbox is the reliability layer for modern target identification and discovery analytics.,"Warm intro from gene-editing, RNA, or drug-discovery circles is ideal.",Medium,https://khoslaventures.com/team/nessan-bermingham,https://khoslaventures.com/,2026-03-08,,,
4,Tier 2,Khosla Ventures,Samir Kaul,Founding Partner and Managing Director,venture fund,Seed-A-B,"Interests span AI, advanced technology, health, sustainability, and food.",Guardant Health; Impossible Foods; Mirvie; Ultima Genomics; Oscar,Samir’s public profile blends large technical ambition with health and AI exposure, plus prior early-stage biotech company creation experience.,"Good fit if Glassbox is pitched as a very large market control-point in AI-enabled biology, not just a narrow lab tool.",Show that reproducibility and verification are trillion-dollar control points as AI enters every stage of life-science R&D.,Best through founder or co-investor intro; focus on category scale and inevitability.,Medium,https://khoslaventures.com/team/samir-kaul,https://khoslaventures.com/,2026-03-08,,,
4,Tier 2,Obvious Ventures,James Joaquin,Co-Founder & Managing Director,venture fund,Seed-A,Invests early in breakthrough technologies and is passionate about the responsible use of AI to solve large problems.,Beyond Meat; Diamond Foundry; Incredible Health,"Obvious announced OV5 in January 2026 and highlighted a generative-science thesis with investments such as Inceptive, Inductive, and Bayesian at the firm level.","Good fit if Glassbox is framed as mission-driven enabling infrastructure for safer, more reliable generative science.",Glassbox helps the AI-in-science stack earn trust and real-world traction rather than staying as paper innovation.,Warm intro preferred; tie strongly to Obvious’s human health and generative science thesis.,Medium,https://obvious.com/team/james-joaquin/,https://obvious.com/,2026-03-08,,,
4,Tier 2,Obvious Ventures,Kahini Shah,Partner,venture fund,Seed-A,Brings product and software experience with a focus on ML and AI-native companies across sectors.,,"Kahini’s profile is AI-native, while Obvious’s recent public writing and fund communications emphasize generative science and human health.","Relevant for an AI-native infrastructure framing, especially if the product feels software-first and data-centric.",Pitch Glassbox as the QA / evaluation / trust layer for AI-native biology products and labs.,"Warm intro, or concise cold note if you can show a strong product wedge and fast deployment path.",Medium,https://obvious.com/team/kahini-shah/,https://obvious.com/,2026-03-08,,,
4,Tier 3,S32,Bill Maris,Founder,venture fund,Seed-A-B,"Founded S32, a venture capital firm investing at the frontiers of technology.",,"Public descriptions of S32 emphasize frontier technology and, in market coverage, the intersection of AI, precision medicine, and computational biology.","Worth tracking because the thesis overlaps with frontier tech and human-condition-improving platforms, though it is a less direct bio-tools target than DCVC/Lux/ARCH.",Pitch Glassbox as frontier tech for scientific reliability in an era of AI-native biology.,"Best through strong network intro from a life-science operator, technical founder, or mutual investor.",Medium,https://www.s32.com/team/bill-maris,https://www.s32.com/,2026-03-08,,,
4,Tier 2,SOSV SF / SOSV NY (formerly IndieBio),Deborah Zajac,"General Partner, SOSV & IndieBio",accelerator / venture fund,Pre-seed-Seed,"General partner with venture and startup experience across deep tech, healthcare, industrial, climate, and consumer solutions.",,"Deborah joined as a general partner and expands IndieBio / SOSV’s deep-tech and healthcare investing reach. Current March 2026 branding is SOSV SF / SOSV NY, though public profile and program pages remain on indiebio.co.",Relevant if Glassbox is still at the wedge-finding stage and could benefit from cross-domain commercialization perspective.,Glassbox is deep-tech enabling infrastructure with immediate healthcare relevance and broader platform potential.,Apply to IndieBio / SOSV and seek targeted introductions through the program team.,High (via application),https://indiebio.co/team/deborah-zajac/,https://indiebio.co/program/,2026-03-08,,,
4,Tier 2,SOSV SF / SOSV NY (formerly IndieBio),Po Bronson,"General Partner, SOSV & Managing Director",accelerator / venture fund,Pre-seed-Seed,Managing Director of IndieBio SF; focused on helping deep-tech founders create something out of nothing.,,"SOSV’s bio programs publicly offer up to $550K pre-seed SAFE, residency, curated investor intros, demo days, and access to a 7,000+ investor network. Current March 2026 branding is SOSV SF / SOSV NY, though public profile and program pages remain on indiebio.co.","Very good fit if Glassbox is early and can benefit from lab access, investor exposure, and tighter product iteration with founders in-program.",Pitch Glassbox as enabling infrastructure that helps AI-bio startups generate trustworthy experimental evidence faster.,Apply through the SOSV / IndieBio program and also cultivate direct relationship through demo days and ecosystem events.,High (via application),https://indiebio.co/team/po-bronson/,https://indiebio.co/program/,2026-03-08,,,
4,Tier 2,SOSV SF / SOSV NY (formerly IndieBio),Stephen Chambers,"General Partner, SOSV & Managing Director",accelerator / venture fund,Pre-seed-Seed,Heads the IndieBio NY program; has a PhD in molecular biology and deep entrepreneurship background in pharma.,,"Stephen leads the NYC bio program and SOSV positions the program around experimentation, iteration, and commercialization support. Current March 2026 branding is SOSV SF / SOSV NY, though public profile and program pages remain on indiebio.co.","Strong fit if you want early validation with therapeutics, biotech tools, and industrial-bio startups in a hands-on setting.",Glassbox shortens the route from experiment to trusted conclusion for startups that are still finding product-market fit.,Apply to the program and reach out around demo day / New York bio startup ecosystem touchpoints.,High (via application),https://indiebio.co/team/stephen-chambers/,https://indiebio.co/program/,2026-03-08,,,
"""


def parse_csv_rows(blob: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(blob.strip())))


def normalize_domain(url: str) -> str:
    parsed = urlparse((url or "").strip())
    return parsed.netloc.replace("www.", "").strip().lower()


def split_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in (full_name or "").strip().split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def score_to_total(priority_score: int) -> int:
    mapping = {5: 95, 4: 82, 3: 68, 2: 52, 1: 35}
    return mapping.get(priority_score, 50)


def score_to_grade(total_score: int, settings) -> str:
    if total_score >= settings.grade_a_min:
        return "A"
    if total_score >= settings.grade_b_min:
        return "B"
    if total_score >= settings.grade_c_min:
        return "C"
    return "D"


def sequence_for_row(row: dict[str, str]) -> str:
    intro = (row.get("intro_path_recommendation") or row.get("best_entry_route") or "").lower()
    outbound = (row.get("cold_outbound_viability") or "").lower()
    if "apply" in intro:
        return "founder_fundraising"
    if "warm intro" in intro:
        return "investor_diligence"
    if "medium" in outbound or "high" in outbound:
        return "investor_diligence"
    return "investor_diligence"


def offer_for_row(row: dict[str, str]) -> str:
    if "apply" in (row.get("intro_path_recommendation") or "").lower():
        return "Program application + founder memo"
    if "warm intro" in (row.get("intro_path_recommendation") or row.get("best_entry_route") or "").lower():
        return "Warm intro + technical memo"
    return "Evidence-driven investor memo"


async def _seed() -> None:
    settings = get_settings()
    await init_db()

    firm_rows = parse_csv_rows(FIRM_CSV)
    person_rows = parse_csv_rows(PERSON_CSV)
    firm_lookup = {row["firm"]: row for row in firm_rows}

    async with AsyncSessionLocal() as session:
        company_index: dict[str, Company] = {}

        for firm_row in firm_rows:
            firm_name = firm_row["firm"].strip()
            company = (
                await session.execute(
                    select(Company).where(Company.name == firm_name)
                )
            ).scalars().one_or_none()
            if company is None:
                company = Company(name=firm_name)
                session.add(company)
                await session.flush()

            company.domain = normalize_domain(firm_row["official_url"])
            company.website = firm_row["official_url"].strip()
            company.industry = firm_row["firm_type"].strip()
            company.funding_stage = firm_row["priority_bucket"].strip()
            company.ai_bio_relevance = float(int(firm_row["priority_score"]) / 5.0)
            company.source_urls = list(dict.fromkeys((company.source_urls or []) + [firm_row["official_url"].strip()]))
            company.cloud_signals = {
                **(company.cloud_signals or {}),
                "priority_score": int(firm_row["priority_score"]),
                "priority_bucket": firm_row["priority_bucket"].strip(),
                "firm_type": firm_row["firm_type"].strip(),
                "why_relevant_for_glassbox": firm_row["why_relevant_for_glassbox"].strip(),
                "public_signal": firm_row["public_signal"].strip(),
                "best_entry_route": firm_row["best_entry_route"].strip(),
                "official_url": firm_row["official_url"].strip(),
                "last_verified": firm_row["last_verified"].strip(),
            }
            company_index[firm_name] = company

            signal = (
                await session.execute(
                    select(Signal).where(
                        Signal.company_id == company.id,
                        Signal.contact_id.is_(None),
                        Signal.type == "investor_firm_profile",
                    )
                )
            ).scalars().one_or_none()
            if signal is None:
                signal = Signal(company_id=company.id, contact_id=None, type="investor_firm_profile", source="glassbox_seed")
                session.add(signal)
            signal.source_url = firm_row["official_url"].strip()
            signal.raw_text = " ".join(
                part
                for part in [
                    firm_row["why_relevant_for_glassbox"].strip(),
                    firm_row["public_signal"].strip(),
                    firm_row["best_entry_route"].strip(),
                ]
                if part
            )
            signal.extracted_summary = firm_row["why_relevant_for_glassbox"].strip()
            signal.confidence = 0.95
            signal.recency_score = 0.8
            signal.metadata_json = {**firm_row}

        for row in person_rows:
            firm_name = row["firm"].strip()
            company = company_index[firm_name]
            first_name, last_name = split_name(row["person"])

            contact = (
                await session.execute(
                    select(Contact).where(Contact.company_id == company.id, Contact.full_name == row["person"].strip())
                )
            ).scalars().one_or_none()
            if contact is None:
                contact = Contact(company_id=company.id, full_name=row["person"].strip())
                session.add(contact)
                await session.flush()

            contact.first_name = first_name
            contact.last_name = last_name
            contact.title = row["title"].strip()
            contact.linkedin_url = row["official_profile_url"].strip() or None
            contact.seniority = row["title"].strip()
            contact.function = "investor"
            contact.inferred_buying_role = "investor"
            contact.email_verified = False

            lead = (
                await session.execute(
                    select(Lead).where(Lead.company_id == company.id, Lead.contact_id == contact.id)
                )
            ).scalars().one_or_none()
            if lead is None:
                lead = Lead(company_id=company.id, contact_id=contact.id)
                session.add(lead)
                await session.flush()

            priority_score = int(row["priority_score"] or firm_lookup[firm_name]["priority_score"])
            total_score = score_to_total(priority_score)
            lead.status = LeadStatus.QUALIFIED if priority_score >= 4 else LeadStatus.RESEARCHED
            lead.icp_class = row["firm_type"].strip()
            lead.persona_class = "investor"
            lead.why_now = [
                item
                for item in [row["why_fit_for_glassbox"].strip(), row["firm_signal"].strip()]
                if item
            ][:4]
            lead.recommended_sequence = sequence_for_row(row)
            lead.recommended_offer = offer_for_row(row)
            lead.confidence = min(0.55 + priority_score * 0.08, 0.95)

            score = (
                await session.execute(
                    select(LeadScore)
                    .where(LeadScore.lead_id == lead.id)
                    .order_by(LeadScore.created_at.desc())
                )
            ).scalars().first()
            if score is None:
                score = LeadScore(lead_id=lead.id)
                session.add(score)
            score.company_fit = int(total_score * 0.3)
            score.persona_fit = int(total_score * 0.2)
            score.trigger_strength = int(total_score * 0.2)
            score.pain_fit = int(total_score * 0.15)
            score.reachability = total_score - score.company_fit - score.persona_fit - score.trigger_strength - score.pain_fit
            score.total_score = total_score
            score.lead_grade = score_to_grade(total_score, settings)
            score.model_confidence = lead.confidence
            score.rationale = {
                "priority_bucket": row["priority_bucket"].strip(),
                "why_fit_for_glassbox": row["why_fit_for_glassbox"].strip(),
                "suggested_pitch_angle": row["suggested_pitch_angle"].strip(),
                "intro_path_recommendation": row["intro_path_recommendation"].strip(),
            }

            signal = (
                await session.execute(
                    select(Signal).where(
                        Signal.company_id == company.id,
                        Signal.contact_id == contact.id,
                        Signal.type == "investor_contact_profile",
                    )
                )
            ).scalars().one_or_none()
            if signal is None:
                signal = Signal(company_id=company.id, contact_id=contact.id, type="investor_contact_profile", source="glassbox_seed")
                session.add(signal)
            signal.source_url = (row["official_profile_url"] or row["official_firm_url"]).strip() or None
            signal.raw_text = " ".join(
                part
                for part in [
                    row["public_focus"].strip(),
                    row["why_fit_for_glassbox"].strip(),
                    row["suggested_pitch_angle"].strip(),
                ]
                if part
            )
            signal.extracted_summary = row["why_fit_for_glassbox"].strip()
            signal.confidence = lead.confidence
            signal.recency_score = 0.8
            signal.metadata_json = {**row}

        await session.commit()

        crm = SheetsCRMService(settings)
        metrics = MetricsService()
        try:
            result = await crm.full_sync(session=session, metrics_service=metrics)
        finally:
            await crm.close()

        lead_count = (await session.execute(select(Lead))).scalars().all()
        company_count = (await session.execute(select(Company))).scalars().all()
        contact_count = (await session.execute(select(Contact))).scalars().all()
        print(
            {
                "companies": len(company_count),
                "contacts": len(contact_count),
                "leads": len(lead_count),
                "sheet_sync": result,
            }
        )


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
