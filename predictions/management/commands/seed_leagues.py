from django.core.management.base import BaseCommand
from django.db import transaction

from predictions.models import League

# (country, tier_1_league, tier_2_league_or_None)
#
# Tier-2 names are omitted (None) for countries whose second division is
# either not clearly defined, semi-professional, or effectively regional
# (e.g. Canada, New Zealand). Everything else lists the recognised top
# two national divisions. Sponsor prefixes are deliberately left off
# (e.g. "Premier League" not "<Sponsor> Premier League") since sponsor
# names change far more often than competition structure.
COUNTRY_LEAGUES = [
    # --- UEFA ---
    ("England", "Premier League", "Championship"),
    ("Scotland", "Scottish Premiership", "Scottish Championship"),
    ("Wales", "Cymru Premier", "Cymru North"),
    ("Northern Ireland", "NIFL Premiership", "NIFL Championship"),
    ("Republic of Ireland", "League of Ireland Premier Division", "League of Ireland First Division"),
    ("France", "Ligue 1", "Ligue 2"),
    ("Germany", "Bundesliga", "2. Bundesliga"),
    ("Italy", "Serie A", "Serie B"),
    ("Spain", "La Liga", "Segunda División"),
    ("Portugal", "Primeira Liga", "Liga Portugal 2"),
    ("Netherlands", "Eredivisie", "Eerste Divisie"),
    ("Belgium", "Belgian Pro League", "Challenger Pro League"),
    ("Switzerland", "Swiss Super League", "Swiss Challenge League"),
    ("Austria", "Austrian Bundesliga", "Austrian 2. Liga"),
    ("Poland", "Ekstraklasa", "I Liga"),
    ("Czech Republic", "Czech First League", "Czech National Football League"),
    ("Slovakia", "Slovak Super Liga", "Slovak 2. Liga"),
    ("Hungary", "NB I", "NB II"),
    ("Romania", "Liga I", "Liga II"),
    ("Bulgaria", "First League", "Second League"),
    ("Serbia", "Serbian SuperLiga", "Serbian First League"),
    ("Croatia", "HNL", "First NL"),
    ("Slovenia", "PrvaLiga", "Second League"),
    ("Bosnia and Herzegovina", "Premier League of Bosnia and Herzegovina", "First League of FBiH"),
    ("North Macedonia", "First Football League", "Second Football League"),
    ("Montenegro", "First League", "Second League"),
    ("Albania", "Kategoria Superiore", "Kategoria e Parë"),
    ("Greece", "Super League Greece", "Super League Greece 2"),
    ("Turkey", "Süper Lig", "TFF First League"),
    ("Cyprus", "Cypriot First Division", "Cypriot Second Division"),
    ("Israel", "Ligat Ha'Al", "Liga Leumit"),
    ("Ukraine", "Ukrainian Premier League", "Ukrainian First League"),
    ("Russia", "Russian Premier League", "Russian First League"),
    ("Belarus", "Belarusian Premier League", "Belarusian First League"),
    ("Moldova", "Moldovan Super Liga", "Moldovan National Division"),
    ("Georgia", "Erovnuli Liga", "Erovnuli Liga 2"),
    ("Armenia", "Armenian Premier League", "Armenian First League"),
    ("Azerbaijan", "Azerbaijan Premier League", "Azerbaijan First Division"),
    ("Kazakhstan", "Kazakhstan Premier League", "Kazakhstan First Division"),
    ("Denmark", "Danish Superliga", "Danish 1st Division"),
    ("Sweden", "Allsvenskan", "Superettan"),
    ("Norway", "Eliteserien", "Norwegian First Division"),
    ("Finland", "Veikkausliiga", "Ykkösliiga"),
    ("Iceland", "Besta deild karla", "1. deild karla"),
    ("Estonia", "Meistriliiga", "Esiliiga"),
    ("Latvia", "Virsliga", "Latvian First League"),
    ("Lithuania", "A Lyga", "I Lyga"),
    ("Luxembourg", "National Division", "Luxembourg 1. Division"),
    ("Malta", "Maltese Premier League", "Maltese Challenge League"),
    ("Andorra", "Primera Divisió", "Segona Divisió"),
    ("San Marino", "Campionato Sammarinese", None),
    ("Gibraltar", "Gibraltar National League", "Gibraltar Second Division"),
    ("Faroe Islands", "Betri deildin", "1. deild"),
    ("Kosovo", "Football Superleague of Kosovo", "First Football League of Kosovo"),

    # --- CONMEBOL ---
    ("Brazil", "Brasileirão Série A", "Brasileirão Série B"),
    ("Argentina", "Liga Profesional de Fútbol", "Primera Nacional"),
    ("Uruguay", "Uruguayan Primera División", "Uruguayan Segunda División"),
    ("Paraguay", "Paraguayan Primera División", "División Intermedia"),
    ("Chile", "Chilean Primera División", "Primera B de Chile"),
    ("Bolivia", "Bolivian Primera División", "Bolivian Segunda División"),
    ("Peru", "Peruvian Primera División", "Peruvian Segunda División"),
    ("Ecuador", "Ecuadorian Serie A", "Ecuadorian Serie B"),
    ("Colombia", "Categoría Primera A", "Categoría Primera B"),
    ("Venezuela", "Venezuelan Primera División", "Venezuelan Segunda División"),

    # --- CONCACAF ---
    ("United States", "Major League Soccer", "USL Championship"),
    ("Mexico", "Liga MX", "Liga de Expansión MX"),
    ("Canada", "Canadian Premier League", None),
    ("Costa Rica", "Liga FPD", "Liga de Ascenso"),
    ("Honduras", "Liga Nacional", "Liga de Ascenso"),
    ("Jamaica", "Jamaica Premier League", None),
    ("Panama", "Liga Panameña de Fútbol", "Liga Nacional de Ascenso"),
    ("Guatemala", "Liga Nacional", "Primera División de Ascenso"),
    ("El Salvador", "Primera División", "Segunda División"),
    ("Trinidad and Tobago", "TT Premier Football League", None),

    # --- AFC ---
    ("Japan", "J1 League", "J2 League"),
    ("South Korea", "K League 1", "K League 2"),
    ("China", "Chinese Super League", "China League One"),
    ("Saudi Arabia", "Saudi Pro League", "Saudi First Division League"),
    ("Qatar", "Qatar Stars League", "Qatari Second Division"),
    ("United Arab Emirates", "UAE Pro League", "UAE First Division League"),
    ("Iran", "Persian Gulf Pro League", "Azadegan League"),
    ("Iraq", "Iraqi Premier League", "Iraqi Division One"),
    ("Australia", "A-League Men", "National Premier Leagues"),
    ("Thailand", "Thai League 1", "Thai League 2"),
    ("Vietnam", "V.League 1", "V.League 2"),
    ("Indonesia", "Liga 1", "Liga 2"),
    ("Uzbekistan", "Uzbekistan Super League", "Uzbekistan First League"),
    ("India", "Indian Super League", "I-League"),
    ("Malaysia", "Malaysia Super League", "Malaysia Premier League"),

    # --- CAF ---
    ("Egypt", "Egyptian Premier League", "Egyptian Second Division"),
    ("Morocco", "Botola Pro", "Botola 2"),
    ("Algeria", "Algerian Ligue Professionnelle 1", "Algerian Ligue Professionnelle 2"),
    ("Tunisia", "Tunisian Ligue Professionnelle 1", "Tunisian Ligue Professionnelle 2"),
    ("Nigeria", "Nigeria Premier Football League", "Nigeria National League"),
    ("Ghana", "Ghana Premier League", "Division One League"),
    ("South Africa", "South African Premier Division", "National First Division"),
    ("Senegal", "Senegal Premier League", "Senegal Ligue 2"),
    ("Ivory Coast", "Ivorian Ligue 1", "Ivorian Ligue 2"),
    ("Cameroon", "Elite One", "Elite Two"),
    ("Kenya", "Kenyan Premier League", "National Super League"),
    ("Zambia", "Zambia Super League", "Zambia National Division 1"),
    ("Tanzania", "Tanzanian Premier League", "Tanzanian First Division League"),
    ("Uganda", "Uganda Premier League", "Uganda Big League"),
    ("DR Congo", "Linafoot", "Ligue de Football Amateur"),
    ("Mali", "Malian Première Division", "Malian Deuxième Division"),
    ("Ethiopia", "Ethiopian Premier League", "Ethiopian Higher League"),

    # --- OFC ---
    ("New Zealand", "New Zealand National League", None),
]


class Command(BaseCommand):
    help = (
        "Seeds the League table with the top two divisions for a wide "
        "range of footballing countries, so the admin has leagues ready "
        "to pick from when adding teams and matches. Safe to re-run — "
        "existing (name, country) pairs are left untouched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            for country, tier1, tier2 in COUNTRY_LEAGUES:
                for league_name in (tier1, tier2):
                    if not league_name:
                        continue
                    if dry_run:
                        exists = League.objects.filter(
                            name=league_name, country=country
                        ).exists()
                        if exists:
                            skipped_count += 1
                        else:
                            created_count += 1
                            self.stdout.write(f"Would create: {league_name} ({country})")
                        continue

                    _, created = League.objects.get_or_create(
                        name=league_name, country=country
                    )
                    if created:
                        created_count += 1
                    else:
                        skipped_count += 1

            if dry_run:
                # Roll back — this is a preview only.
                transaction.set_rollback(True)

        verb = "Would create" if dry_run else "Created"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created_count} league(s); {skipped_count} already existed. "
            f"Covered {len(COUNTRY_LEAGUES)} countries."
        ))