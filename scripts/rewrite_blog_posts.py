"""Rewrite the four tecas-solar.com articles into the Odoo blog, signed "Tecas".

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/rewrite_blog_posts.py

What it does, all idempotent:
  * rewrites the four posts (matched by title, never by id, so it survives a
    re-import) with the content below;
  * adds one new post on solar pumping — the catalogue's biggest family and
    the one the site now advertises in the menu;
  * sets a cover on each rewritten post from the picture the old site used;
  * signs EVERY post in the blog "Tecas", replacing OdooBot / BRAHIM /
    "tecas energie solaire" and friends;
  * fills teaser and meta description, which drive the cards and the search
    snippet.

Editorial decisions worth knowing, because they change what the client's
readers are told:
  * The originals quoted FRENCH incentives — crédit d'impôt CITE, prime à
    l'autoconsommation, TVA réduite, "économiser 5 000 euros par an" — none of
    which exist for a Moroccan customer. They are gone rather than translated.
    Nothing was invented to replace them: the texts talk about the savings and
    the payback, and send the reader to our teams for anything scheme-related.
  * The fourth article was published as an OUTLINE ("Exemple : X euros",
    "Schéma détaillé", "L'énergie solaire en France"). It is written out here.
  * Dated facts were updated (the 2020 horizon of the Plan solaire is history;
    Noor Ouarzazate has been running for years). Figures are deliberately round
    and few — every one of them should be confirmed by the client before this
    is treated as marketing collateral.
"""

import base64
import json
import re
from urllib.request import urlopen, Request

BLOG_ID = 1
AUTHOR_NAME = 'Tecas'
OLD_SITE = 'https://tecas-solar.com'

CTA = (
    '<p><a href="/demande-devis" class="btn btn-primary">Demander un devis gratuit</a>'
    ' &nbsp; <a href="/shop" class="btn btn-secondary">Voir le matériel</a></p>'
)

POST_MAROC = """
<p>Le soleil est une source d'énergie propre, abondante et inépuisable, et il est
réparti de façon presque uniforme sur le globe. L'énergie solaire que la Terre
reçoit en une seule heure suffirait à couvrir les besoins énergétiques de
l'humanité pendant un an. Le Maroc, pays de soleil, dispose de l'un des
gisements les plus intéressants au monde.</p>

<h2>Un gisement solaire parmi les meilleurs au monde</h2>
<p>La grande majorité du territoire marocain bénéficie de plus de 3 000 heures
d'ensoleillement par an. Cette ressource est stable, prévisible et disponible
partout : du littoral atlantique aux plaines agricoles, jusqu'aux régions du
Sud où le rayonnement est le plus fort. C'est ce qui rend le photovoltaïque
aussi pertinent pour une villa de Casablanca que pour une exploitation agricole
isolée.</p>

<h2>Du Plan solaire marocain à Noor Ouarzazate</h2>
<p>Lancé en novembre 2009, le Plan solaire marocain a fait du Royaume un
précurseur régional des énergies renouvelables. Il a donné naissance à la MASEN
(Moroccan Agency for Sustainable Energy) et à un programme de grands sites de
production, dont le plus emblématique est le complexe <strong>Noor
Ouarzazate</strong>, en service depuis la seconde moitié des années 2010 et
longtemps la plus grande centrale solaire concentrée au monde. D'autres sites
ont suivi, notamment à Midelt, Boujdour, Laâyoune et Aïn Beni Mathar.</p>
<p>Le pays s'est fixé un objectif clair : porter la part des énergies
renouvelables à plus de la moitié de sa puissance électrique installée à
l'horizon 2030. Cette trajectoire ne concerne pas que les grands projets
publics — elle s'accompagne d'une ouverture progressive à l'autoproduction, qui
permet aux particuliers, aux entreprises et aux exploitations agricoles de
produire l'électricité qu'ils consomment.</p>

<h2>Ce que le solaire change pour l'environnement</h2>
<ul>
  <li><strong>Moins de gaz à effet de serre.</strong> Une installation
  photovoltaïque produit de l'électricité sans rejeter de CO₂ ni de polluants
  atmosphériques. Chaque kilowattheure produit sur un toit marocain est un
  kilowattheure qui n'a pas été produit à partir de combustibles fossiles.</li>
  <li><strong>Moins de ressources consommées.</strong> Le solaire n'épuise
  aucune ressource : le combustible est gratuit et illimité, ce qui allège la
  facture énergétique du pays comme celle de ses habitants.</li>
  <li><strong>Une meilleure qualité de l'air.</strong> Moins de combustion,
  c'est moins de particules et moins de risques sanitaires dans les zones
  urbaines denses.</li>
</ul>

<h2>Un moteur d'emplois et de compétences</h2>
<p>L'essor du solaire crée des métiers à tous les niveaux de qualification :
études et dimensionnement, pose et raccordement, maintenance, distribution de
matériel. Il fait aussi monter en compétence des filières entières —
électricité, génie civil, mécanique — et développe une chaîne locale de
services. C'est un secteur qui forme autant qu'il recrute.</p>

<h2>Et pour vous, concrètement ?</h2>
<p>La transition énergétique marocaine ne se joue pas uniquement dans le désert :
elle se joue aussi sur les toits. Un système photovoltaïque bien dimensionné
réduit durablement votre facture d'électricité et vous protège de ses hausses
futures. Nous vous accompagnons du dimensionnement à la mise en service, avec
du matériel choisi pour durer : <a href="/shop/category/panneaux-solaire-286">panneaux
solaires</a>, <a href="/shop/category/onduleurs-solaires-364">onduleurs</a> et
<a href="/shop/category/batteries-solaires-289">batteries</a>.</p>
""" + CTA

POST_PRIX = """
<p>L'énergie solaire séduit de plus en plus de particuliers et de professionnels
au Maroc. Face à la hausse des factures d'électricité, installer des panneaux
solaires est devenu une solution durable et économique. Reste la question que
l'on nous pose tous les jours : <strong>combien coûte une installation solaire
au Maroc ?</strong> Voici ce qui fait le prix, et comment éviter de payer pour
ce dont vous n'avez pas besoin.</p>

<h2>1. Ce qui fait le prix d'un panneau solaire</h2>
<p>Il n'existe pas un prix du panneau solaire, mais une fourchette qui dépend de
quatre facteurs :</p>
<ul>
  <li><strong>La puissance</strong> du module (400 W, 550 W, 600 W et plus) :
  c'est elle qui détermine combien de panneaux couvriront vos besoins.</li>
  <li><strong>La technologie</strong> : monofacial ou bifacial, half-cut,
  N-Type… Un module bifacial produit davantage sur une toiture réfléchissante
  ou sur structure au sol, mais il ne se justifie pas partout.</li>
  <li><strong>La marque et les certifications</strong>, qui déterminent surtout
  la garantie de rendement et la solidité du recours en cas de défaut.</li>
  <li><strong>Le type de projet</strong> : résidentiel, agricole ou industriel
  n'imposent ni les mêmes contraintes mécaniques ni les mêmes protections.</li>
</ul>
<p>Retrouvez les marques et puissances disponibles dans notre rayon
<a href="/shop/category/panneaux-solaire-286">panneaux solaires</a>.</p>

<h2>2. Ce que comprend une installation complète</h2>
<p>Le panneau ne fait qu'un tiers du budget. Une installation, c'est :</p>
<ul>
  <li>les <a href="/shop/category/panneaux-solaire-286">panneaux</a> ;</li>
  <li>l'<a href="/shop/category/onduleurs-solaires-364">onduleur</a> — on-grid,
  off-grid ou hybride selon que vous restez raccordé au réseau ou non ;</li>
  <li>la structure de fixation, adaptée à votre toiture ou au sol ;</li>
  <li>les <a href="/shop/category/coffret-de-protections-acdc-291">protections
  AC/DC</a>, le câblage et les connecteurs ;</li>
  <li>en option, des <a href="/shop/category/batteries-solaires-289">batteries</a>
  pour consommer votre production la nuit ;</li>
  <li>la pose et la mise en service par un professionnel.</li>
</ul>

<h2>3. Pourquoi l'investissement est rentable au Maroc</h2>
<p>Le soleil est abondant dans toutes les régions du pays, et le prix de
l'électricité, lui, ne baisse pas. Une installation photovoltaïque vous permet
de réduire fortement votre facture, de rentabiliser votre investissement en
quelques années, de valoriser votre bien et de gagner en indépendance
énergétique — un argument décisif là où les coupures sont fréquentes.</p>

<h2>4. Comment choisir le bon matériel</h2>
<p>Quatre données suffisent pour partir sur de bonnes bases : votre
consommation annuelle en kWh (elle figure sur vos factures), la surface
réellement exploitable et son orientation, votre besoin ou non de stockage, et
le niveau de performance visé. Un dimensionnement honnête part de votre
consommation, jamais d'un catalogue.</p>

<h2>5. Les erreurs qui coûtent cher</h2>
<ul>
  <li><strong>Surdimensionner.</strong> Produire beaucoup plus que ce que vous
  consommez allonge le retour sur investissement au lieu de le raccourcir.</li>
  <li><strong>Économiser sur l'onduleur.</strong> C'est la pièce qui travaille
  le plus et la première à lâcher sur du matériel bas de gamme.</li>
  <li><strong>Négliger les protections.</strong> Un coffret DC et un parafoudre
  corrects coûtent une fraction de l'installation qu'ils protègent.</li>
  <li><strong>Oublier la maintenance.</strong> Des panneaux poussiéreux, sous
  notre climat, c'est plusieurs pour cent de production en moins.</li>
</ul>

<h2>6. Demander un devis personnalisé</h2>
<p>Chaque projet est unique. Nos équipes évaluent votre consommation,
sélectionnent le matériel adapté, estiment les économies possibles et vous
remettent un devis clair. Livraison partout au Maroc.</p>
""" + CTA

POST_RENTABLE = """
<p>L'énergie solaire est bien plus qu'une tendance : c'est une décision
économique. Pour une entreprise comme pour un particulier, une installation
photovoltaïque est un investissement dont le rendement se mesure sur des
décennies, pas sur une saison.</p>

<h2>Une technologie éprouvée et durable</h2>
<ul>
  <li><strong>Longévité exceptionnelle.</strong> Les panneaux solaires ont une
  durée de vie de 25 à 30 ans, souvent davantage. Leur rendement diminue
  lentement — les garanties constructeurs portent d'ailleurs sur une puissance
  encore élevée au bout de 25 ans.</li>
  <li><strong>Entretien minimal.</strong> Un nettoyage régulier et un contrôle
  visuel annuel suffisent dans la grande majorité des cas.</li>
  <li><strong>Résistance aux intempéries.</strong> Les modules sont conçus et
  testés pour la grêle, le vent et les écarts de température ; sous climat
  marocain, c'est surtout la poussière qui demande de l'attention.</li>
</ul>

<h2>Des économies qui se cumulent</h2>
<p>Produire son électricité, c'est acheter moins de kilowattheures au réseau.
L'économie est immédiate, elle se répète chaque mois, et elle grandit à mesure
que les tarifs augmentent. Deux chiffres à retenir avant de signer :</p>
<ul>
  <li><strong>votre consommation annuelle en kWh</strong>, lue sur vos factures
  — c'est la seule base sérieuse de calcul ;</li>
  <li><strong>votre taux d'autoconsommation</strong>, c'est-à-dire la part de
  votre production que vous consommez réellement. Une entreprise qui travaille
  le jour atteint naturellement un taux élevé : c'est le profil le plus
  rentable, sans batterie.</li>
</ul>
<p>Un particulier dont la consommation est surtout nocturne obtiendra un autre
équilibre, et c'est là que le <a href="/shop/category/batteries-solaires-289">stockage</a>
prend son sens. Nous simulons ces deux scénarios pour vous avant tout
engagement.</p>

<h2>Une valorisation de votre patrimoine</h2>
<p>Un bâtiment équipé se loue et se revend mieux : l'acheteur ou le locataire
hérite d'une facture d'électricité réduite et d'un équipement encore sous
garantie. Pour un local professionnel, c'est aussi un argument commercial et
environnemental.</p>

<h2>Un retour sur investissement rapide</h2>
<p>Grâce aux économies réalisées et à la longévité des installations, le retour
sur investissement se compte généralement en <strong>quelques années</strong>,
puis l'installation continue de produire pendant deux décennies ou plus. La
durée exacte dépend de votre consommation, de votre profil horaire et du
matériel retenu — méfiez-vous de quiconque vous annonce un chiffre avant
d'avoir vu vos factures.</p>

<h2>Ce qu'il faut vérifier avant de signer</h2>
<ul>
  <li>Les garanties : produit, rendement, onduleur, et la pose elle-même.</li>
  <li>La disponibilité du service après-vente et des pièces au Maroc.</li>
  <li>Le dimensionnement : sur quelle consommation réelle est-il calculé ?</li>
  <li>Les protections électriques, trop souvent absentes des devis les plus
  bas.</li>
</ul>

<h2>En conclusion</h2>
<p>Le solaire est un investissement sûr, lisible et rentable sur le long terme.
Vous y gagnez une facture réduite, une énergie propre et une indépendance qui
n'a plus de prix les jours de coupure. Nos équipes réalisent l'étude, fournissent
le matériel et assurent le suivi.</p>
""" + CTA

POST_PRODUISEZ = """
<p>Installer des panneaux solaires sur votre toit, c'est produire vous-même une
partie — parfois la totalité — de l'électricité que vous consommez. Voici,
simplement, comment cela fonctionne et comment s'y prendre.</p>

<h2>Comment fonctionne une installation solaire</h2>
<p>Une cellule photovoltaïque transforme directement la lumière du soleil en
courant électrique continu. Les cellules sont assemblées en panneaux, les
panneaux en champ. L'onduleur convertit ensuite ce courant continu en courant
alternatif, celui de vos prises et de vos appareils. Il n'y a aucune pièce en
mouvement dans ce processus : c'est ce qui explique la longévité et le faible
entretien de ces installations.</p>

<h3>Les composants</h3>
<ul>
  <li><strong>Les <a href="/shop/category/panneaux-solaire-286">panneaux</a></strong> :
  ils produisent. Leur puissance et leur technologie déterminent la surface
  nécessaire.</li>
  <li><strong>L'<a href="/shop/category/onduleurs-solaires-364">onduleur</a></strong> :
  il convertit, surveille et protège. C'est le cerveau de l'installation.</li>
  <li><strong>La structure de fixation</strong> : elle assure la tenue au vent
  et l'étanchéité de la toiture.</li>
  <li><strong>Les <a href="/shop/category/coffret-de-protections-acdc-291">protections
  AC/DC</a></strong> : coffrets, parafoudre, sectionneurs — la sécurité de
  l'ensemble.</li>
  <li><strong>Les <a href="/shop/category/batteries-solaires-289">batteries</a></strong>,
  optionnelles : elles décalent votre production vers le soir.</li>
</ul>

<h2>Les trois façons de produire</h2>
<ul>
  <li><strong>L'autoconsommation raccordée au réseau.</strong> Vous consommez
  votre production en direct et le réseau prend le relais la nuit. C'est le
  montage le plus simple et le plus rentable quand on consomme le jour.</li>
  <li><strong>L'hybride avec stockage.</strong> Le surplus de la journée est
  stocké puis restitué le soir. Plus d'autonomie, un budget plus élevé.</li>
  <li><strong>Le site isolé (off-grid).</strong> Pas de réseau du tout : le
  dimensionnement du parc de batteries devient le cœur du projet. C'est la
  solution des fermes, des puits et des sites éloignés.</li>
</ul>

<h2>Bien dimensionner son installation</h2>
<p>Le bon dimensionnement part de trois éléments : votre consommation annuelle
(en kWh, sur vos factures), la surface exploitable avec son orientation et son
inclinaison, et votre profil d'utilisation — consommez-vous surtout le jour ou
le soir ? Une orientation sud avec une inclinaison proche de 30° reste la
référence sous nos latitudes, mais une toiture est-ouest bien exploitée donne
d'excellents résultats.</p>

<h2>Les étapes d'une installation</h2>
<ol>
  <li>Étude et dimensionnement à partir de vos factures.</li>
  <li>Devis détaillé : matériel, pose, garanties.</li>
  <li>Pose des structures et des panneaux.</li>
  <li>Raccordement électrique, protections et mise en service.</li>
  <li>Prise en main : suivi de production et bons réflexes.</li>
</ol>
<p>Un chantier résidentiel courant se réalise en quelques jours.</p>

<h2>Entretien et garanties</h2>
<p>Comptez un nettoyage périodique — indispensable en zone poussiéreuse ou
agricole — et une vérification annuelle des connexions et des protections.
Conservez les garanties : celle des panneaux (produit et rendement), celle de
l'onduleur, et celle de la pose.</p>

<h2>Conclusion</h2>
<p>Produire son électricité est aujourd'hui simple, fiable et rentable. La
seule vraie question est celle du dimensionnement : ni trop, ni trop peu, et
adapté à votre façon de consommer. C'est exactement le travail que nous
faisons avec vous avant de vous vendre quoi que ce soit.</p>
""" + CTA

POST_POMPAGE = """
<p>Le pompage solaire est l'une des applications les plus rentables du
photovoltaïque au Maroc : le besoin en eau est maximal quand le soleil est au
plus haut, ce qui permet souvent de se passer complètement de batteries. Encore
faut-il dimensionner correctement — une pompe mal choisie coûte deux fois : à
l'achat, puis en production perdue.</p>

<h2>Pourquoi le pompage solaire s'impose</h2>
<ul>
  <li>Aucune facture de carburant, contrairement à un groupe électrogène.</li>
  <li>Aucun réseau à tirer jusqu'à la parcelle.</li>
  <li>Un entretien réduit, et un fonctionnement automatique au fil du soleil.</li>
  <li>Un bassin ou un château d'eau qui sert de « batterie » gratuite.</li>
</ul>

<h2>Immergée, de surface ou vide-cave : laquelle ?</h2>
<ul>
  <li><strong>Pompe immergée</strong> : pour un puits ou un forage. Elle
  travaille sous l'eau et pousse vers la surface. C'est le cas le plus fréquent
  en irrigation.</li>
  <li><strong>Pompe de surface</strong> : installée hors de l'eau, elle aspire
  depuis un bassin, une rivière ou une citerne. Idéale pour les faibles
  profondeurs.</li>
  <li><strong>Pompe vide-cave</strong> : pour évacuer, vidanger ou assécher —
  un usage ponctuel, pas un usage d'irrigation.</li>
</ul>

<h2>Les cinq données à réunir avant de choisir</h2>
<ol>
  <li>Le <strong>débit</strong> nécessaire, en m³ par jour.</li>
  <li>La <strong>hauteur manométrique totale</strong> (HMT) : dénivelé, pertes
  de charge et pression en sortie réunis.</li>
  <li>La <strong>profondeur du forage</strong> et le <strong>niveau dynamique</strong>
  de l'eau en pompage — pas seulement le niveau au repos.</li>
  <li>Le <strong>diamètre du forage</strong>, qui conditionne le corps de pompe.</li>
  <li>La <strong>qualité de l'eau</strong> : sable et salinité imposent des
  matériaux adaptés, l'inox par exemple.</li>
</ol>
<p>Avec ces cinq valeurs, le choix de la pompe et du champ solaire devient un
calcul, plus une intuition.</p>

<h2>Le champ solaire et le variateur</h2>
<p>La puissance du champ photovoltaïque se dimensionne sur celle de la pompe,
avec une marge pour les heures moins ensoleillées. Le variateur de vitesse
adapte la fréquence au rayonnement disponible : la pompe démarre plus tôt le
matin, ralentit quand un nuage passe et protège le moteur contre la marche à
sec. C'est lui qui fait la différence entre une installation qui produit toute
la journée et une qui ne travaille qu'à midi.</p>

<h2>Entretien</h2>
<p>Nettoyage des modules, contrôle des protections, vérification du niveau
dynamique et surveillance de l'usure du corps de pompe : quelques gestes
simples suffisent à tenir des années.</p>

<h2>Parlons de votre projet</h2>
<p>Nous fournissons les <a href="/shop/category/pompes-383">pompes solaires</a>,
les panneaux, les variateurs et les accessoires, et nous vous aidons à
dimensionner l'ensemble à partir des données de votre forage.</p>
""" + CTA

POSTS = [
    {
        'match': "L'Énergie Solaire au Maroc",
        'name': "L'Énergie Solaire au Maroc : Un Avenir Lumineux pour l'Environnement",
        'content': POST_MAROC,
        'teaser': "Plus de 3 000 heures de soleil par an, un Plan solaire lancé dès 2009 et "
                  "Noor Ouarzazate en vitrine : où en est le Maroc, et ce que cela change sur "
                  "votre toit.",
        'meta': "Le Maroc et l'énergie solaire : gisement, Plan solaire marocain, Noor "
                "Ouarzazate, bénéfices environnementaux et emplois. Par Tecas Energie Solaire.",
        'tags': ['Environnement', 'Panneau solaire'],
        'cover': '/wp-content/uploads/2025/12/Maison-Villa.jpg',
        'date': '2026-03-26 09:00:00',
    },
    {
        'match': "Panneau solaire prix Maroc",
        'name': "Panneau solaire prix Maroc : ce qu'il faut savoir avant de vous équiper",
        'content': POST_PRIX,
        'teaser': "Ce qui fait vraiment le prix d'un panneau et d'une installation complète au "
                  "Maroc, comment choisir son matériel et les erreurs qui coûtent cher.",
        'meta': "Prix des panneaux solaires au Maroc : ce qui fait varier le tarif, le coût "
                "d'une installation complète et comment choisir. Devis gratuit Tecas.",
        'tags': ['Panneau solaire', 'Prix'],
        'cover': '/wp-content/uploads/2026/03/01JZTAMVPP82NT8T9S3C4SQTYY.png',
        'date': '2026-03-26 08:00:00',
    },
    {
        'match': "investissement rentable",
        'name': "Le solaire : un investissement rentable à long terme, les chiffres à l'appui",
        'content': POST_RENTABLE,
        'teaser': "Durée de vie, économies cumulées, valorisation du bâtiment et retour sur "
                  "investissement : ce qu'il faut regarder — et vérifier — avant de signer.",
        'meta': "Rentabilité d'une installation solaire au Maroc : longévité, économies, "
                "retour sur investissement et points à vérifier avant de signer.",
        'tags': ['Rentabilité', 'Panneau solaire'],
        'cover': '/wp-content/uploads/2025/12/'
                 'Le-solaire-un-investissement-rentable-a-long-terme.jpeg',
        'date': '2025-12-16 09:00:00',
    },
    {
        'match': "Produisez votre propre",
        'name': "L'énergie solaire : Produisez votre propre électricité et faites des économies",
        'content': POST_PRODUISEZ,
        'teaser': "Comment fonctionne une installation, quels composants, autoconsommation ou "
                  "site isolé, dimensionnement, étapes du chantier et entretien.",
        'meta': "Produire son électricité au Maroc : fonctionnement, composants, "
                "autoconsommation ou site isolé, dimensionnement, installation et entretien.",
        'tags': ['Autoconsommation', 'Panneau solaire'],
        'cover': '/wp-content/uploads/2025/12/an-informative-infographic-with-the-title-'
                 'l-energi-jfsB0yKxQeW_pyWhURVLjQ-s7TsZ7hVQ0i8odxPU8LPnw.jpeg',
        'date': '2025-12-16 08:00:00',
    },
    {
        # New: the pump range is the biggest family in the catalogue and the
        # site now advertises it in the menu, but nothing on the blog spoke to
        # the farmers who buy it.
        'match': "Pompage solaire",
        'name': "Pompage solaire : bien dimensionner sa pompe avant d'acheter",
        'content': POST_POMPAGE,
        'teaser': "Immergée, de surface ou vide-cave, débit, HMT, niveau dynamique : les cinq "
                  "données qui décident du bon choix, et le rôle du variateur.",
        'meta': "Pompage solaire au Maroc : choisir entre pompe immergée, de surface ou "
                "vide-cave, calculer débit et HMT, dimensionner le champ solaire.",
        'tags': ['Panneau solaire'],
        'cover': None,
        'create': True,
    },
]

Post = env['blog.post'].sudo()
Tag = env['blog.tag'].sudo()
Attachment = env['ir.attachment'].sudo()
report = []

# --- the author -----------------------------------------------------------
# A dedicated partner, not the company's own record: that one carries the
# addresses and the accounting links, and renaming it would rewrite the
# company's name on every document it appears on.
author = env['res.partner'].sudo().search([('name', '=', AUTHOR_NAME)], limit=1)
if not author:
    # tecas_extention/models/res_partner.py demands a phone on an individual
    # and an ICE on a company — data-entry guards meant for real contacts. A
    # blog byline is neither, and must not end up carrying an invented phone
    # number or tax identifier. So the record is created with a placeholder
    # that is cleared in the same transaction (write() only re-validates a
    # phone when one is actually set), leaving a partner with a name and
    # nothing else.
    placeholder = '+212000000000'
    if env['res.partner'].sudo().search_count([('phone', '=', placeholder)]):
        raise SystemExit('the placeholder phone is in use; pick another one')
    author = env['res.partner'].sudo().create({'name': AUTHOR_NAME, 'phone': placeholder})
    author.write({'phone': False})
    report.append('created the author partner "%s" (%s)' % (AUTHOR_NAME, author.id))
if not author.image_1920:
    logo = env['res.company'].sudo().browse(1).logo
    if logo:
        author.write({'image_1920': logo})
        report.append('gave the author the company logo as avatar')


def fetch_cover(path):
    """Download a picture from the old site and store it as a public attachment."""
    name = path.rsplit('/', 1)[-1]
    existing = Attachment.search([('name', '=', name), ('res_model', '=', 'blog.post')], limit=1)
    if existing:
        return existing
    request = Request(OLD_SITE + path, headers={'User-Agent': 'tecas-migration/1.0'})
    data = urlopen(request, timeout=30).read()
    attachment = Attachment.create({
        'name': name,
        'datas': base64.b64encode(data),
        'res_model': 'blog.post',
        'public': True,
        'mimetype': 'image/png' if name.lower().endswith('.png') else 'image/jpeg',
    })
    report.append('downloaded %s (%d kB)' % (name, len(data) // 1024))
    return attachment


def set_cover(post, path):
    attachment = fetch_cover(path)
    url = '/web/image/%s-%s/%s' % (attachment.id, attachment.checksum[:8], attachment.name)
    properties = {}
    try:
        properties = json.loads(post.cover_properties or '{}')
    except ValueError:
        properties = {}
    properties.update({
        'background-image': 'url("%s")' % url,
        'background_color_class': properties.get('background_color_class', 'o_cc3'),
        'opacity': properties.get('opacity', '0.2'),
        'resize_class': properties.get('resize_class', 'o_half_screen_height'),
    })
    post.write({'cover_properties': json.dumps(properties)})
    return url


for spec in POSTS:
    # A new post is matched on its exact title, never on a fragment: "Pompage
    # solaire" also matches the old "Installation pompage solaire" stub, and
    # the first run of this script overwrote it. An existing post is matched on
    # a fragment but must resolve to exactly one — two matches means the
    # fragment is wrong, and rewriting the wrong article is worse than doing
    # nothing.
    if spec.get('create'):
        matches = Post.with_context(active_test=False).search(
            [('blog_id', '=', BLOG_ID), ('name', '=', spec['name'])])
    else:
        matches = Post.with_context(active_test=False).search(
            [('blog_id', '=', BLOG_ID), ('name', 'ilike', spec['match'])])
    if len(matches) > 1:
        report.append('AMBIGUOUS, skipped: "%s" matches %d posts (%s)'
                      % (spec['match'], len(matches),
                         ', '.join((p.name or '')[:30] for p in matches)))
        continue
    post = matches[:1]
    if not post:
        if not spec.get('create'):
            report.append('NOT FOUND, skipped: %s' % spec['match'])
            continue
        post = Post.create({
            'blog_id': BLOG_ID,
            'name': spec['name'],
            'content': spec['content'],
            'is_published': True,
        })
        report.append('created "%s" (%s)' % (spec['name'], post.id))

    tags = Tag.browse()
    for tag_name in spec['tags']:
        tag = Tag.search([('name', '=', tag_name)], limit=1) or Tag.create({'name': tag_name})
        tags |= tag

    values = {
        'name': spec['name'],
        'content': spec['content'],
        'teaser_manual': spec['teaser'],
        'website_meta_description': spec['meta'],
        'author_id': author.id,
        # author_name is a stored field of its own, not a mirror of author_id:
        # setting only the partner leaves the old byline ("BRAHIM") on the card.
        'author_name': AUTHOR_NAME,
        'tag_ids': [(6, 0, tags.ids)],
        'is_published': True,
    }
    post.write(values)
    # post_date last, and in its own write: publishing a post stamps it with
    # the current time, so setting it in the same values would be overwritten.
    # The dates are the ones the articles carry on tecas-solar.com — without
    # them the four posts land seconds apart and the blog lists them in the
    # order the script happened to process them.
    if spec.get('date') and str(post.post_date) != spec['date']:
        post.write({'post_date': spec['date']})
    if spec.get('cover'):
        set_cover(post, spec['cover'])
    report.append('rewrote "%s" (%s), %d characters' % (spec['name'], post.id, len(spec['content'])))

# --- every other post keeps its content but is signed by Tecas ------------
others = Post.with_context(active_test=False).search(
    ['|', ('author_id', '!=', author.id), ('author_name', '!=', AUTHOR_NAME)])
if others:
    others.write({'author_id': author.id, 'author_name': AUTHOR_NAME})
    report.append('re-signed %d other post(s): %s'
                  % (len(others), ', '.join((p.name or '')[:28] for p in others)))

env.cr.commit()
print('\n--- blog rewrite ---')
for line in report:
    print(' *', line)
print('\nauthors now:', set(Post.with_context(active_test=False).search([]).mapped('author_id.name')))
