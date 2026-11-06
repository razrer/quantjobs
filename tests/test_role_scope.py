"""The user's quant-finance scope, including its protected boundary cases."""
import unittest

from quantscraper import role_scope, tagging


def exclusion(title, description=""):
    return role_scope.exclusion(tagging.fold(title), tagging.fold(description), description)


class RoleScopeTest(unittest.TestCase):
    def test_rejected_support_variants(self):
        for title in (
            "Sr HR Consultant (Generalist)", "People Direct Advisor",
            "Ekonomi- och personalansvarig till Epton Trading",
            "Associate, HR Technology and Analytics", "Settlement Analyst",
            "Backoffice Administrator - Mutual Funds", "Junior Depositary Officer",
            "Fondadministratör på deltid", "Värdepappersadministratör",
            "Relationship Associate - Public Sector Banking",
        ):
            with self.subTest(title=title):
                self.assertEqual(exclusion(title)[0], "non_quant_finance")

    def test_named_office_it_does_not_need_a_body(self):
        for title in (
            "Microsoft 365 Specialist med Exchange-bakgrund",
            "Application Specialist Microsoft Dynamics 365 (Junior)",
            "Expert IT Analyst - Mainframe Swedish Core Systems",
            "IT Infrastructure Specialist - Nordea Life & Pension",
        ):
            with self.subTest(title=title):
                self.assertEqual(exclusion(title)[0], "generic_it")
        self.assertIsNone(exclusion("Software Engineer - Group Treasury"))
        self.assertIsNone(exclusion("Information Architect, Group Data Management"))

    def test_quantitative_welfare_analysis_is_not_financial_markets(self):
        body = "Ansvar och arbetsuppgifter\nDu analyserar upplägg och metoder som används i välfärdsbrottsligheten. Vi använder Python och SQL.\nVi söker dig som har\nAkademisk examen."
        self.assertEqual(exclusion("Kvantitativ analytiker", body)[0], "off_industry")
        # The same phrase in an employer intro or previous-experience list
        # must not exclude a markets role.
        for body in (
            "Vi förebygger välfärdsbrott. Arbetsuppgifter: Utveckla modeller för kreditrisk.\nVi söker dig som har erfarenhet.",
            "Arbetsuppgifter: Utveckla modeller för kreditrisk.\nVi söker dig som har erfarenhet av välfärdsbrott.",
        ):
            with self.subTest(body=body):
                self.assertIsNone(exclusion("Kvantitativ analytiker", body))
        self.assertIsNone(exclusion("Kvantitativ analytiker"))

    def test_executive_research_requires_recruitment_duties(self):
        self.assertEqual(exclusion("Executive Researcher - Talent", "What you will do: Own market mapping and longlisting for board searches. Run first candidate contact.")[0], "non_quant_finance")
        self.assertIsNone(exclusion("Executive Researcher", "Responsibilities: Develop alpha signals and backtest trading strategies."))
        self.assertIsNone(exclusion("Executive Researcher"))

    def test_conventional_finance_is_out_even_at_a_quant_firm(self):
        for title in (
            "Portfolio Manager", "Treasury Analyst", "Equity Research Associate",
            "Investment Banking Analyst", "Fund Accountant", "Legal Counsel, Trading",
            "Senior Portföljförvaltare Index", "Financial Reporting Analyst",
            "Product Controller", "Risk Governance Analyst", "Global Markets Compliance",
        ):
            with self.subTest(title=title):
                self.assertEqual(exclusion(title)[0], "non_quant_finance")

    def test_trading_and_named_quant_work_stay(self):
        for title in (
            "Graduate Trader", "Treasury Trader", "FX Cash Trader", "Assistant Trader",
            "Systematic Portfolio Manager", "Portfolio Optimization Researcher",
            "Risk Model Developer", "Model Validation Analyst", "Quantitative Analyst",
            "Kvantitativ analytiker", "Derivatives Pricing Engineer",
            "Software Engineer - Research Technology", "Securities Risk/Pricing Engineer",
        ):
            with self.subTest(title=title):
                self.assertIsNone(exclusion(title))

    def test_body_can_rescue_a_generic_finance_title(self):
        self.assertIsNone(exclusion("Portfolio Analyst", "Responsibilities: Develop and backtest factor models for systematic strategies. Requirements: Python."))
        self.assertIsNone(exclusion("Treasury Analyst", "Your role: Build and calibrate quantitative models for derivatives pricing. Qualifications: MSc."))

    def test_a_quant_flavoured_fund_seat_stays(self):
        """The user's rule: fund roles only if quant or adjacent."""
        robur = (
            "Hos oss får du arbeta med indexnära förvaltning. Använda data, modeller och "
            "programmering för att systematisera investeringsprocesser. Bidra inom riskanalys "
            "och optimering. Du har kvantitativa kunskaper och läst matematik."
        )
        self.assertIsNone(exclusion("Senior Portföljförvaltare Index till Swedbank Robur", robur))
        entelios = (
            "Det här kommer du att arbeta med • använda GenAI och data för att utveckla "
            "modeller, informationsflöden och beslutsstöd • följa energimarknaden. "
            "Vi söker dig som har läst matematik, kan Python och har kvantitativ förmåga."
        )
        self.assertIsNone(exclusion("Portföljförvaltare - Å Entelios", entelios))

    def test_a_fund_house_risk_or_allocation_seat_is_adjacent(self):
        self.assertIsNone(exclusion("Riskanalytiker inom kapitalförvaltning"))
        self.assertIsNone(exclusion("Senior Portfolio Manager – Asset Allocation till AP7"))

    def test_a_fund_house_internship_is_not_a_fund_seat(self):
        self.assertEqual(exclusion(
            "Wealth & Asset Management Internship 2027: Risk Analyst Intern"
        )[0], "non_quant_finance")

    def test_an_engineering_title_is_not_a_fund_seat(self):
        quantish = "Python and machine learning. Statistics and quantitative methods."
        for title in ("AI Solution Engineer (Asset Management & Reliability)",
                      "Software Engineer in Asset Management (m/w/d)"):
            with self.subTest(title=title):
                self.assertEqual(exclusion(title, quantish * 40)[0], "generic_it")

    def test_a_conventional_fund_seat_stays_out(self):
        for title, body in (
            ("Alecta söker aktieförvaltare inom Financials",
             "Ansvara för en aktivt förvaltad portfölj och portföljkonstruktion. "
             "Arbeta ihop med aktieanalytiker vid aktieurval och dialoger med bolag."),
            ("AP3 söker två globala aktieförvaltare",
             "Definiera och utveckla strategin för ditt mandat. Du har goda kunskaper i Python."),
            ("Ränteförvaltare till Swedbank Robur",
             "Du får en betydande frihet i din förvaltning och ett stort eget ansvar."),
            ("Kapitalförvaltare", "Ha ett eget affärsansvar för din kundbas."),
        ):
            with self.subTest(title=title):
                self.assertEqual(exclusion(title, body)[0], "non_quant_finance")

    def test_risk_control_outside_a_fund_house_is_still_conventional(self):
        self.assertEqual(exclusion("Operational Risk Analyst")[0], "non_quant_finance")

    def test_swedish_duties_count_as_duties(self):
        self.assertIsNone(exclusion(
            "Treasury Analyst",
            "Använda statistiska modeller för att mäta likviditeten. Du har en examen.",
        ))
        self.assertEqual(exclusion(
            "Treasury Analyst", "Vi på bolaget har statistiska modeller. Du har en examen.",
        )[0], "non_quant_finance")

    def test_financial_modelling_and_python_are_not_quant_proof(self):
        self.assertEqual(exclusion("Equity Research Analyst", "Responsibilities: Build financial models, DCF valuations and earnings forecasts in Python. Write stock recommendations.")[0], "non_quant_finance")

    def test_employer_boilerplate_and_skills_do_not_rescue_support(self):
        body = "About us: We develop systematic strategies and pricing models. Responsibilities: Prepare cash balances and liquidity reports. Requirements: Experience developing quantitative models."
        self.assertEqual(exclusion("Treasury Analyst", body)[0], "non_quant_finance")
        self.assertEqual(exclusion("Legal Counsel, Quantitative Research", body)[0], "non_quant_finance")

    def test_generic_it_vs_trading_technology(self):
        body = "Responsibilities: Build internal HR applications and maintain employee portals. Requirements: Python, SQL, cloud engineering. " * 3
        self.assertEqual(exclusion("Software Engineer", body)[0], "generic_it")
        self.assertEqual(exclusion("Systems: Network Reliability Engineer")[0], "generic_it")
        self.assertIsNone(exclusion("Software Engineer", "Responsibilities: <ul><li><b>Develop</b> trading platforms and execution algorithms.</li></ul> Requirements: Python."))

    def test_missing_evidence_and_unrelated_unknown_titles_are_not_rejections(self):
        for title in ("Software Developer", "Applied AI Engineer", "Risk Analyst", "Analyst", "Systemutvecklare Kapitalförvaltning"):
            with self.subTest(title=title):
                self.assertIsNone(exclusion(title))

    def test_aggregator_navigation_teaser_is_not_a_full_body(self):
        body = "Fejlmeld annonce. Join our innovative fintech company. " * 6
        self.assertIsNone(exclusion("Software Engineer Valuation Product Area", body))

    def test_action_applies_to_following_noun_bullets(self):
        body = "<p>Your Role</p><p>You will build our:</p><ul><li>Model computation and signal generation pipeline</li></ul><p>What You’ll Bring</p><p>Python experience</p>"
        self.assertIsNone(exclusion("Portfolio Management Engineer", body))

    def test_requirements_word_inside_duty_does_not_end_section(self):
        body = "RESPONSIBILITIES Build data pipelines under correctness requirements. Develop live trading systems. REQUIREMENTS Experience with Python."
        self.assertIn(" develop live trading systems ", role_scope._duties(body)[0])
        self.assertIsNone(exclusion("Portfolio Management Engineer", body))

    def test_scope_vocabulary_is_in_fingerprint(self):
        from unittest.mock import patch
        before = tagging.fingerprint()
        with patch.object(role_scope, "FINANCE_TITLES", role_scope.FINANCE_TITLES + ("new scope phrase",)):
            self.assertNotEqual(before, tagging.fingerprint())

    def test_narrative_trading_duties_and_research_compute(self):
        for body in (
            "The position duties are as follows: Develop software for trading and operational infrastructure. The position requires Python experience.",
            "At our company, our Software Engineer Interns work directly with engineers to develop low latency proprietary trading systems.",
            "Responsibilities: Design and maintain HPC compute and storage infrastructure. Qualifications: Linux.",
            "Role Summary: You will build a real time data distribution system. Responsibilities: Develop components. Qualifications: Python.",
            "Role Summary: We are seeking a software engineer for our real time data distribution system. Responsibilities: Build components. Qualifications: Python.",
        ):
            with self.subTest(body=body):
                self.assertIsNone(exclusion("Portfolio Management Engineer", body))

    def test_bring_heading_ends_duties(self):
        body = "<p>Your Role</p><p>Build employee portals.</p><p>What You’ll Bring</p><p>Experience developing quantitative models.</p>" * 4
        self.assertEqual(exclusion("Software Engineer", body)[0], "generic_it")


if __name__ == "__main__":
    unittest.main()
