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
