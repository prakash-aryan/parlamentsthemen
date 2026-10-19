export type Lang = "de" | "fr" | "it" | "rm" | "en";
export type Level = "" | "country" | "canton" | "city" | "municipality";
export type Verdict = "yes" | "likely" | "unsure" | "no";
export type NoteKey = "n_curia" | "n_sg";

export const LANGS: Lang[] = ["de", "fr", "it", "rm", "en"];
export const LEVELS: Level[] = ["", "country", "canton", "city", "municipality"];

export interface Dict {
  title: string;
  parl: string;
  topright: string;
  langs: string;
  h1a: string;
  h1b: string;
  lede: string;
  footer: string;
  federal: string;
  failed: string;
  s_num: string;
  s_h2: string;
  s_placeholder: string;
  s_go: string;
  f_topic: string;
  f_none: string;
  f_level: string;
  f_from: string;
  f_to: string;
  levels: Record<"all" | "country" | "canton" | "city" | "municipality", string>;
  g_adhoc: string;
  g_curia: string;
  g_sg: string;
  g_aps: string;
  r_note_stored: string;
  ov_head: string;
  ov_line: string;
  ov_line_one: string;
  ov_pool: string;
  ov_pool_topic: string;
  ov_hint: string;
  ov_only: string;
  ov_all: string;
  ov_closed: string;
  examples: string[];
  r_count: string;
  r_count_topic: string;
  r_count_browse: string;
  r_none: string;
  r_none_qt: string;
  r_none_topic: string;
  r_loading: string;
  r_loading_topic: string;
  r_open: string;
  r_similar: string;
  r_type: string;
  r_state: string;
  r_date: string;
  r_hint: string;
  dym: string;
  r_hint_qt: string;
  r_note_browse: string;
  r_note_qt: string;
  r_empty: string;
  why: string;
  quote_hint: string;
  verdict: Record<Verdict, string>;
  t_head: string;
  t_loading: string;
  t_none: string;
  t_wrong: string;
  t_reported: string;
  t_pick: string;
  flag: string;
  flagged: string;
  title_only: string;
  adhoc: Record<string, string>;
  n_curia: string;
  n_sg: string;
  n_years: string;
  n_reset: string;
  canvas: string[];
  f_year: string;
  f_more: string;
  f_less: string;
  ex_more: string;
  f_body: string;
  f_body_all: string;
  since2024: string;
  r_sorted_rel: string;
  r_sorted_year: string;
  r_total: string;
  updating: string;
  details_show: string;
  details_hide: string;
  auto_check: string;
  context_show: string;
  context_hide: string;
  ev_loading: string;
  ev_failed: string;
  retry: string;
  flag_failed: string;
  no: string;
  original: string;
  langnames: Record<"de" | "fr" | "it" | "rm" | "en", string>;
  bodies: Record<string, string>;
  title_only_short: string;
  ov_show: string;
  ov_hide: string;
  rv_mode: string;
  rv_login: string;
  rv_name: string;
  rv_code: string;
  rv_enter: string;
  rv_exit: string;
  rv_active: string;
  rv_bad: string;
  rv_queue: string;
  rv_none: string;
  rv_yes: string;
  rv_no: string;
  rv_add: string;
  rv_saved: string;
  rv_failed: string;
  rv_reviewed: string;
  rv_orig: string;
  rv_removed: string;
  rv_hint: string;
  rv_nostore: string;
  rv_yesno_yes: string;
  rv_yesno_no: string;
  listen: string;
  listen_stop: string;
  listen_loading: string;
  listen_results: string;
  mic: string;
  mic_stop: string;
  mic_listening: string;
  mic_working: string;
  mic_failed: string;
}

export const I18N: Record<Lang, Dict> = {
  de: {
    ov_show: "Nach Parlament anzeigen", ov_hide: "Parlamente ausblenden",
    rv_mode: "Prüfmodus", rv_login: "Für Prüfende", rv_name: "Name", rv_code: "Zugangscode", rv_enter: "Anmelden", rv_exit: "Prüfmodus beenden", rv_active: "Prüfmodus: {n}", rv_bad: "Der Zugangscode ist falsch.", rv_queue: "Offene Meldungen", rv_none: "Keine offenen Meldungen.", rv_yes: "Trifft zu", rv_no: "Trifft nicht zu", rv_add: "Thema hinzufügen …", rv_saved: "gespeichert", rv_failed: "Speichern fehlgeschlagen", rv_reviewed: "geprüft", rv_orig: "Ursprünglicher Vorschlag: {d}", rv_removed: "entfernt", rv_hint: "Ihre Entscheidung ersetzt den Vorschlag des Modells; der ursprüngliche Vorschlag bleibt gespeichert.", rv_nostore: "Für dieses Thema ist noch keine gespeicherte Zuordnung vorhanden.", rv_yesno_yes: "ja", rv_yesno_no: "nein",
    listen: "Vorlesen", listen_stop: "Vorlesen beenden", listen_loading: "Wird vorbereitet …", listen_results: "Ergebnisse vorlesen", mic: "Suche sprechen", mic_stop: "Aufnahme beenden", mic_listening: "Sprechen Sie jetzt. Zum Beenden erneut auf das Mikrofon drücken.", mic_working: "Ihre Suche wird erkannt …", mic_failed: "Die Aufnahme hat nicht funktioniert. Bitte den Zugriff auf das Mikrofon erlauben oder die Suche eintippen.",
    f_year: "Jahr", f_more: "Weitere Filter", f_less: "Weniger Filter", ex_more: "Weitere Beispiele", f_body: "Parlament", f_body_all: "Alle Parlamente", since2024: "Seit 2024", r_sorted_rel: "nach Relevanz sortiert", r_sorted_year: "nach Jahr sortiert", r_total: "{t} Geschäfte zum Thema insgesamt", updating: "Ergebnisse werden aktualisiert …", details_show: "Details anzeigen", details_hide: "Details ausblenden", auto_check: "Automatische Zuordnung, bitte prüfen.", context_show: "Kontext anzeigen", context_hide: "Kontext ausblenden", ev_loading: "Beleg wird geladen …", ev_failed: "Der Beleg konnte nicht geladen werden.", retry: "Erneut versuchen", flag_failed: "Die Meldung ist fehlgeschlagen.", no: "Nr.", original: "Original: {l}", langnames: {"de": "Deutsch", "fr": "Französisch", "it": "Italienisch", "rm": "Rätoromanisch", "en": "Englisch"}, title_only_short: "nur Titel", bodies: {"ZH": "Zürich", "BE": "Bern", "LU": "Luzern", "UR": "Uri", "SZ": "Schwyz", "OW": "Obwalden", "NW": "Nidwalden", "GL": "Glarus", "ZG": "Zug", "FR": "Freiburg", "SO": "Solothurn", "BS": "Basel-Stadt", "BL": "Basel-Landschaft", "SH": "Schaffhausen", "AR": "Appenzell Ausserrhoden", "AI": "Appenzell Innerrhoden", "SG": "St. Gallen", "GR": "Graubünden", "AG": "Aargau", "TG": "Thurgau", "TI": "Tessin", "VD": "Waadt", "VS": "Wallis", "NE": "Neuenburg", "GE": "Genf", "JU": "Jura", "CHE": "Schweiz"},
    g_aps: "Standardthemen (Année Politique Suisse)", r_note_stored: "Die neuesten Treffer zum Thema, nach Jahr sortiert. Der Überblick zählt alle Geschäfte zum Thema.", ov_head: "Überblick", ov_line: "{n} Geschäfte in {p} Parlamenten", ov_line_one: "{n} Geschäfte in 1 Parlament", ov_pool: "Unter den {k} passendsten Geschäften", ov_pool_topic: "Unter den {k} Geschäften, die dem Thema am nächsten sind", ov_hint: "Ein Parlament anklicken, um die Treffer darauf einzuschränken.", ov_only: "Nur {b}", ov_all: "Alle Parlamente", ov_closed: "«Erledigt ohne Angabe» heisst: Das Parlament meldet nur, dass das Geschäft abgeschlossen ist, nicht wie es ausging.",
    title: "Parlamentsthemen", parl: "Parlamente", topright: "Bund · Kantone · Städte · Gemeinden", langs: "Sprache",
    h1a: "Parlaments", h1b: "themen",
    lede: "Geschäfte (Motionen, Anfragen und Vorlagen) aus allen Schweizer Parlamenten finden: nach Thema, Satz oder Stichwort, in jeder Landessprache.",
    footer: "Daten: OpenParlData.ch. Themen werden automatisch zugeordnet; falsche Zuordnungen können gemeldet werden.",
    federal: "Bund", failed: "Die Suche ist fehlgeschlagen. Bitte später erneut versuchen.",
    s_num: "Suche", s_h2: "Was beschäftigt die Parlamente?", s_placeholder: "Satz oder Stichwort, zum Beispiel: Velowege in der Stadt", s_go: "Suchen",
    f_topic: "Nur Geschäfte zum Thema", f_none: "Alle Themen", f_level: "Ebene", f_from: "ab Jahr", f_to: "bis Jahr",
    levels: {"all": "alle Ebenen", "country": "Bund", "canton": "Kanton", "city": "Stadt", "municipality": "Gemeinde"},
    g_adhoc: "Themen für alle Parlamente", g_curia: "Sachbereiche des Bundesparlaments", g_sg: "Sachbereiche des Kantons St. Gallen",
    examples: ["Künstliche Intelligenz in der Verwaltung", "Velowege und Verkehrssicherheit", "bezahlbarer Wohnraum", "Cyberangriffe auf Spitäler"],
    r_count: "{n} angezeigte Treffer zu «{q}»", r_count_topic: "{n} angezeigte Treffer zu «{q}» im Thema «{t}»",
    r_none: "Keine Treffer.", r_loading: "Suche läuft …",
    r_open: "Originalseite", r_similar: "Ähnliche Geschäfte", r_type: "Art", r_state: "Stand", r_date: "Datum",
    dym: "Meinten Sie: «{q}»?", r_hint: "Suche in eigenen Worten, auch in anderen Landessprachen. Ein Thema grenzt die Treffer ein.",
    why: "Warum", quote_hint: "Vorgeschlagener Beleg. Bitte im Kontext prüfen.",
    verdict: {"yes": "Thema vorgeschlagen", "likely": "Möglicher Bezug", "unsure": "unklar", "no": "nicht vorgeschlagen"},
    t_head: "Themen dieses Geschäfts", t_loading: "Themen werden bestimmt …", t_none: "Keinem Thema eindeutig zugeordnet.",
    t_wrong: "prüfen lassen", t_reported: "zur Prüfung gemeldet", t_pick: "Nach diesem Thema suchen",
    flag: "«{t}» fraglich? Prüfung anfragen", flagged: "Danke. Die Zuordnung ist zur Prüfung vorgemerkt.",
    title_only: "Für dieses Geschäft ist nur der Titel verfügbar.",
    adhoc: {digitalisation: "Digitalisierung"},
    r_count_browse: "{n} angezeigte Treffer im Thema «{t}»",
    r_note_browse: "Ausgewählte Treffer zum Thema, nach Jahr sortiert. Mit einem Suchbegriff lässt sich die Liste eingrenzen.",
    r_note_qt: "Gezeigt werden nur Treffer, die dem Thema «{t}» zugeordnet sind.",
    r_empty: "Geben Sie einen Suchbegriff ein oder wählen Sie ein Thema.",
    r_loading_topic: "Suche läuft, die Treffer werden dem Thema zugeordnet …",
    n_curia: "Die Sachbereiche des Bundesparlaments gelten nur für Geschäfte des Bundes. Die Ebene ist deshalb auf «Bund» festgelegt.",
    n_sg: "Die Sachbereiche des Kantons St. Gallen gelten nur für Geschäfte des Kantons St. Gallen. Die Suche ist deshalb auf diesen Kanton beschränkt.",
    n_years: "«Ab Jahr» lag nach «bis Jahr». Die beiden Jahre wurden getauscht.",
    n_reset: "Das Thema «{t}» gilt nicht für diese Ebene und wurde entfernt.",
    r_none_qt: "Keine der {c} besten Treffer zu «{q}» gehört zum Thema «{t}».", r_none_topic: "Zum Thema «{t}» wurden keine Geschäfte gefunden.",
    r_hint_qt: "Versuchen Sie einen anderen Suchbegriff oder lassen Sie das Suchfeld leer, um alle Geschäfte zum Thema zu sehen.",
    canvas: ["Digitalisierung", "Verkehr", "Umwelt", "Gesundheit", "Migration", "Energie", "Bildung"],
  },
  fr: {
    ov_show: "Afficher par parlement", ov_hide: "Masquer les parlements",
    rv_mode: "Mode de vérification", rv_login: "Pour les vérificateurs", rv_name: "Nom", rv_code: "Code d'accès", rv_enter: "Se connecter", rv_exit: "Quitter le mode de vérification", rv_active: "Mode de vérification : {n}", rv_bad: "Le code d'accès est incorrect.", rv_queue: "Signalements ouverts", rv_none: "Aucun signalement ouvert.", rv_yes: "Pertinent", rv_no: "Non pertinent", rv_add: "Ajouter un thème …", rv_saved: "enregistré", rv_failed: "Échec de l'enregistrement", rv_reviewed: "vérifié", rv_orig: "Proposition initiale : {d}", rv_removed: "retiré", rv_hint: "Votre décision remplace la proposition du modèle ; la proposition initiale reste enregistrée.", rv_nostore: "Aucune attribution n'est encore enregistrée pour ce thème.", rv_yesno_yes: "oui", rv_yesno_no: "non",
    listen: "Écouter", listen_stop: "Arrêter la lecture", listen_loading: "Préparation …", listen_results: "Écouter les résultats", mic: "Dicter la recherche", mic_stop: "Arrêter l'enregistrement", mic_listening: "Parlez maintenant. Appuyez de nouveau sur le micro pour terminer.", mic_working: "Reconnaissance de votre recherche …", mic_failed: "L'enregistrement n'a pas fonctionné. Autorisez l'accès au micro ou saisissez la recherche.",
    f_year: "Année", f_more: "Autres filtres", f_less: "Moins de filtres", ex_more: "Autres exemples", f_body: "Parlement", f_body_all: "Tous les parlements", since2024: "Depuis 2024", r_sorted_rel: "triés par pertinence", r_sorted_year: "triés par année", r_total: "{t} objets sur le thème au total", updating: "Mise à jour des résultats …", details_show: "Afficher les détails", details_hide: "Masquer les détails", auto_check: "Attribution automatique, à vérifier.", context_show: "Voir le contexte", context_hide: "Masquer le contexte", ev_loading: "Chargement de l'extrait …", ev_failed: "L'extrait n'a pas pu être chargé.", retry: "Réessayer", flag_failed: "Le signalement a échoué.", no: "N°", original: "Original : {l}", langnames: {"de": "allemand", "fr": "français", "it": "italien", "rm": "romanche", "en": "anglais"}, title_only_short: "titre seul", bodies: {"ZH": "Zurich", "BE": "Berne", "LU": "Lucerne", "UR": "Uri", "SZ": "Schwytz", "OW": "Obwald", "NW": "Nidwald", "GL": "Glaris", "ZG": "Zoug", "FR": "Fribourg", "SO": "Soleure", "BS": "Bâle-Ville", "BL": "Bâle-Campagne", "SH": "Schaffhouse", "AR": "Appenzell Rhodes-Extérieures", "AI": "Appenzell Rhodes-Intérieures", "SG": "Saint-Gall", "GR": "Grisons", "AG": "Argovie", "TG": "Thurgovie", "TI": "Tessin", "VD": "Vaud", "VS": "Valais", "NE": "Neuchâtel", "GE": "Genève", "JU": "Jura", "CHE": "Suisse"},
    g_aps: "Thèmes standard (Année Politique Suisse)", r_note_stored: "Les résultats les plus récents sur le thème, triés par année. La vue d'ensemble compte tous les objets du thème.", ov_head: "Vue d'ensemble", ov_line: "{n} objets dans {p} parlements", ov_line_one: "{n} objets dans 1 parlement", ov_pool: "Parmi les {k} objets les plus pertinents", ov_pool_topic: "Parmi les {k} objets les plus proches du thème", ov_hint: "Cliquez sur un parlement pour limiter les résultats à celui-ci.", ov_only: "Seulement {b}", ov_all: "Tous les parlements", ov_closed: "« Liquidé sans précision » signifie que le parlement indique seulement que l'objet est clos, pas son issue.",
    title: "Thèmes parlementaires", parl: "parlements", topright: "Confédération · cantons · villes · communes", langs: "Langue",
    h1a: "Thèmes", h1b: "parlementaires",
    lede: "Trouvez les objets parlementaires (motions, questions et projets) de tous les parlements suisses par thème, phrase ou mot-clé, dans chaque langue nationale.",
    footer: "Données : OpenParlData.ch. Les thèmes sont attribués automatiquement ; une attribution erronée peut être signalée.",
    federal: "Confédération", failed: "La recherche a échoué. Veuillez réessayer plus tard.",
    s_num: "Recherche", s_h2: "De quoi parlent les parlements ?", s_placeholder: "Phrase ou mot-clé, par exemple : pistes cyclables en ville", s_go: "Chercher",
    f_topic: "Seulement les objets sur le thème", f_none: "Tous les thèmes", f_level: "Niveau", f_from: "dès l'année", f_to: "jusqu'en",
    levels: {"all": "tous les niveaux", "country": "Confédération", "canton": "Canton", "city": "Ville", "municipality": "Commune"},
    g_adhoc: "Thèmes pour tous les parlements", g_curia: "Domaines du Parlement fédéral", g_sg: "Domaines du canton de Saint-Gall",
    examples: ["intelligence artificielle dans l'administration", "pistes cyclables", "logements abordables", "cyberattaques contre les hôpitaux"],
    r_count: "{n} résultats affichés pour « {q} »", r_count_topic: "{n} résultats affichés pour « {q} » dans le thème « {t} »",
    r_none: "Aucun résultat.", r_loading: "Recherche en cours …",
    r_open: "Page d'origine", r_similar: "Objets similaires", r_type: "Type", r_state: "État", r_date: "Date",
    dym: "Vouliez-vous dire : « {q} » ?", r_hint: "Recherchez avec vos propres mots, dans une langue nationale. Un thème permet de filtrer les résultats.",
    why: "Pourquoi", quote_hint: "Extrait proposé. À vérifier dans son contexte.",
    verdict: {"yes": "Thème proposé", "likely": "Lien possible", "unsure": "incertain", "no": "non proposé"},
    t_head: "Thèmes de cet objet", t_loading: "Recherche des thèmes …", t_none: "Aucun thème attribué avec certitude.",
    t_wrong: "faire vérifier", t_reported: "signalé pour vérification", t_pick: "Chercher ce thème",
    flag: "« {t} » douteux ? Demander une vérification", flagged: "Merci. L'attribution est notée pour vérification.",
    title_only: "Seul le titre de cet objet est disponible.",
    adhoc: {digitalisation: "Numérisation"},
    r_count_browse: "{n} résultats affichés dans le thème « {t} »",
    r_note_browse: "Résultats choisis sur le thème, triés par année. Un terme de recherche permet de préciser la liste.",
    r_note_qt: "Seuls les résultats attribués au thème « {t} » sont affichés.",
    r_empty: "Saisissez un terme de recherche ou choisissez un thème.",
    r_loading_topic: "Recherche en cours, les résultats sont attribués au thème …",
    n_curia: "Les domaines du Parlement fédéral ne s'appliquent qu'aux objets de la Confédération. Le niveau est donc fixé sur « Confédération ».",
    n_sg: "Les domaines du canton de Saint-Gall ne s'appliquent qu'aux objets de ce canton. La recherche est donc limitée au canton de Saint-Gall.",
    n_years: "« Dès l'année » était postérieure à « jusqu'en ». Les deux années ont été inversées.",
    n_reset: "Le thème « {t} » ne s'applique pas à ce niveau et a été retiré.",
    r_none_qt: "Aucun des {c} meilleurs résultats pour « {q} » ne relève du thème « {t} ».", r_none_topic: "Aucun objet n'a été trouvé sur le thème « {t} ».",
    r_hint_qt: "Essayez un autre terme ou laissez le champ de recherche vide pour voir tous les objets du thème.",
    canvas: ["Numérisation", "Transports", "Environnement", "Santé", "Migration", "Énergie", "Formation"],
  },
  it: {
    ov_show: "Mostra per parlamento", ov_hide: "Nascondi i parlamenti",
    rv_mode: "Modalità di verifica", rv_login: "Per i revisori", rv_name: "Nome", rv_code: "Codice di accesso", rv_enter: "Accedi", rv_exit: "Esci dalla modalità di verifica", rv_active: "Modalità di verifica: {n}", rv_bad: "Il codice di accesso è errato.", rv_queue: "Segnalazioni aperte", rv_none: "Nessuna segnalazione aperta.", rv_yes: "Pertinente", rv_no: "Non pertinente", rv_add: "Aggiungi un tema …", rv_saved: "salvato", rv_failed: "Salvataggio non riuscito", rv_reviewed: "verificato", rv_orig: "Proposta originale: {d}", rv_removed: "rimosso", rv_hint: "La sua decisione sostituisce la proposta del modello; la proposta originale resta salvata.", rv_nostore: "Per questo tema non è ancora salvata alcuna attribuzione.", rv_yesno_yes: "sì", rv_yesno_no: "no",
    listen: "Ascolta", listen_stop: "Ferma la lettura", listen_loading: "Preparazione …", listen_results: "Ascolta i risultati", mic: "Detta la ricerca", mic_stop: "Ferma la registrazione", mic_listening: "Parli ora. Prema di nuovo il microfono per terminare.", mic_working: "Riconoscimento della ricerca …", mic_failed: "La registrazione non è riuscita. Consenta l'accesso al microfono o digiti la ricerca.",
    f_year: "Anno", f_more: "Altri filtri", f_less: "Meno filtri", ex_more: "Altri esempi", f_body: "Parlamento", f_body_all: "Tutti i parlamenti", since2024: "Dal 2024", r_sorted_rel: "ordinati per pertinenza", r_sorted_year: "ordinati per anno", r_total: "{t} oggetti sul tema in totale", updating: "Aggiornamento dei risultati …", details_show: "Mostra dettagli", details_hide: "Nascondi dettagli", auto_check: "Attribuzione automatica, da verificare.", context_show: "Mostra il contesto", context_hide: "Nascondi il contesto", ev_loading: "Caricamento del passaggio …", ev_failed: "Il passaggio non ha potuto essere caricato.", retry: "Riprova", flag_failed: "La segnalazione non è riuscita.", no: "n.", original: "Originale: {l}", langnames: {"de": "tedesco", "fr": "francese", "it": "italiano", "rm": "romancio", "en": "inglese"}, title_only_short: "solo titolo", bodies: {"ZH": "Zurigo", "BE": "Berna", "LU": "Lucerna", "UR": "Uri", "SZ": "Svitto", "OW": "Obvaldo", "NW": "Nidvaldo", "GL": "Glarona", "ZG": "Zugo", "FR": "Friburgo", "SO": "Soletta", "BS": "Basilea Città", "BL": "Basilea Campagna", "SH": "Sciaffusa", "AR": "Appenzello Esterno", "AI": "Appenzello Interno", "SG": "San Gallo", "GR": "Grigioni", "AG": "Argovia", "TG": "Turgovia", "TI": "Ticino", "VD": "Vaud", "VS": "Vallese", "NE": "Neuchâtel", "GE": "Ginevra", "JU": "Giura", "CHE": "Svizzera"},
    g_aps: "Temi standard (Année Politique Suisse)", r_note_stored: "I risultati più recenti sul tema, ordinati per anno. La panoramica conta tutti gli oggetti del tema.", ov_head: "Panoramica", ov_line: "{n} oggetti in {p} parlamenti", ov_line_one: "{n} oggetti in 1 parlamento", ov_pool: "Tra i {k} oggetti più pertinenti", ov_pool_topic: "Tra i {k} oggetti più vicini al tema", ov_hint: "Cliccate su un parlamento per limitare i risultati a quest'ultimo.", ov_only: "Solo {b}", ov_all: "Tutti i parlamenti", ov_closed: "«Evaso senza indicazione» significa che il parlamento indica solo che l'oggetto è chiuso, non il suo esito.",
    title: "Temi parlamentari", parl: "parlamenti", topright: "Confederazione · cantoni · città · comuni", langs: "Lingua",
    h1a: "Temi", h1b: "parlamentari",
    lede: "Trovate gli oggetti parlamentari (mozioni, interrogazioni e progetti) di tutti i parlamenti svizzeri per tema, frase o parola chiave, in ogni lingua nazionale.",
    footer: "Dati: OpenParlData.ch. I temi sono attribuiti automaticamente; un'attribuzione errata può essere segnalata.",
    federal: "Confederazione", failed: "La ricerca non è riuscita. Riprovare più tardi.",
    s_num: "Ricerca", s_h2: "Di cosa si occupano i parlamenti?", s_placeholder: "Frase o parola chiave, ad esempio: piste ciclabili in città", s_go: "Cerca",
    f_topic: "Solo oggetti sul tema", f_none: "Tutti i temi", f_level: "Livello", f_from: "dall'anno", f_to: "fino al",
    levels: {"all": "tutti i livelli", "country": "Confederazione", "canton": "Cantone", "city": "Città", "municipality": "Comune"},
    g_adhoc: "Temi per tutti i parlamenti", g_curia: "Settori del Parlamento federale", g_sg: "Settori del Cantone di San Gallo",
    examples: ["intelligenza artificiale nell'amministrazione", "piste ciclabili", "alloggi a prezzi accessibili", "attacchi informatici agli ospedali"],
    r_count: "{n} risultati mostrati per «{q}»", r_count_topic: "{n} risultati mostrati per «{q}» nel tema «{t}»",
    r_none: "Nessun risultato.", r_loading: "Ricerca in corso …",
    r_open: "Pagina originale", r_similar: "Oggetti simili", r_type: "Tipo", r_state: "Stato", r_date: "Data",
    dym: "Forse cercavi: «{q}»?", r_hint: "Cercate con parole vostre, anche in altre lingue nazionali. Un tema restringe i risultati.",
    why: "Perché", quote_hint: "Passaggio proposto. Da verificare nel contesto.",
    verdict: {"yes": "Tema proposto", "likely": "Possibile legame", "unsure": "incerto", "no": "non proposto"},
    t_head: "Temi di questo oggetto", t_loading: "Ricerca dei temi …", t_none: "Nessun tema attribuito con certezza.",
    t_wrong: "far verificare", t_reported: "segnalato per verifica", t_pick: "Cerca questo tema",
    flag: "«{t}» dubbio? Chiedere una verifica", flagged: "Grazie. L'attribuzione è segnata per la verifica.",
    title_only: "Per questo oggetto è disponibile solo il titolo.",
    adhoc: {digitalisation: "Digitalizzazione"},
    r_count_browse: "{n} risultati mostrati nel tema «{t}»",
    r_note_browse: "Risultati scelti sul tema, ordinati per anno. Un termine di ricerca permette di restringere l'elenco.",
    r_note_qt: "Sono mostrati solo i risultati attribuiti al tema «{t}».",
    r_empty: "Inserite un termine di ricerca o scegliete un tema.",
    r_loading_topic: "Ricerca in corso, i risultati vengono attribuiti al tema …",
    n_curia: "I settori del Parlamento federale valgono solo per gli oggetti della Confederazione. Il livello è quindi fissato su «Confederazione».",
    n_sg: "I settori del Cantone di San Gallo valgono solo per gli oggetti di questo cantone. La ricerca è quindi limitata al Cantone di San Gallo.",
    n_years: "«Dall'anno» era successivo a «fino al». I due anni sono stati scambiati.",
    n_reset: "Il tema «{t}» non vale per questo livello ed è stato rimosso.",
    r_none_qt: "Nessuno dei {c} migliori risultati per «{q}» rientra nel tema «{t}».", r_none_topic: "Non è stato trovato alcun oggetto sul tema «{t}».",
    r_hint_qt: "Provate un altro termine o lasciate vuoto il campo di ricerca per vedere tutti gli oggetti del tema.",
    canvas: ["Digitalizzazione", "Trasporti", "Ambiente", "Salute", "Migrazione", "Energia", "Formazione"],
  },
  rm: {
    ov_show: "Mussar tenor parlament", ov_hide: "Zuppentar ils parlaments",
    rv_mode: "Modus da controlla", rv_login: "Per controlladras e controlladers", rv_name: "Num", rv_code: "Code d'access", rv_enter: "S'annunziar", rv_exit: "Terminar il modus da controlla", rv_active: "Modus da controlla: {n}", rv_bad: "Il code d'access è sbaglià.", rv_queue: "Annunzias avertas", rv_none: "Naginas annunzias avertas.", rv_yes: "Correspunda", rv_no: "Na correspunda betg", rv_add: "Agiuntar in tema …", rv_saved: "memorisà", rv_failed: "La memorisaziun n'è betg reussida", rv_reviewed: "controllà", rv_orig: "Proposta originala: {d}", rv_removed: "allontanà", rv_hint: "Vossa decisiun remplazza la proposta dal model; la proposta originala resta memorisada.", rv_nostore: "Per quest tema n'exista anc nagina attribuziun memorisada.", rv_yesno_yes: "gea", rv_yesno_no: "na",
    listen: "Tadlar", listen_stop: "Fermar la lectura", listen_loading: "Vegn preparà …", listen_results: "Tadlar ils resultats", mic: "Dir la tschertga", mic_stop: "Fermar la registraziun", mic_listening: "Discurri ussa. Smatgai anc ina giada sin il microfon per terminar.", mic_working: "Vossa tschertga vegn reconuschida …", mic_failed: "La registraziun n'ha betg funcziunà. Permettai l'access al microfon u endatai la tschertga.",
    f_year: "Onn", f_more: "Ulteriurs filters", f_less: "Damain filters", ex_more: "Ulteriurs exempels", f_body: "Parlament", f_body_all: "Tut ils parlaments", since2024: "Dapi 2024", r_sorted_rel: "zavrads tenor relevanza", r_sorted_year: "zavrads tenor onn", r_total: "{t} fatgs tar il tema en total", updating: "Ils resultats vegnan actualisads …", details_show: "Mussar detagls", details_hide: "Zuppentar detagls", auto_check: "Attribuziun automatica, per plaschair controllar.", context_show: "Mussar il context", context_hide: "Zuppentar il context", ev_loading: "Il passadi vegn chargià …", ev_failed: "Il passadi n'ha betg pudì vegnir chargià.", retry: "Empruvar anc ina giada", flag_failed: "L'annunzia n'è betg reussida.", no: "Nr.", original: "Original: {l}", langnames: {"de": "tudestg", "fr": "franzos", "it": "talian", "rm": "rumantsch", "en": "englais"}, title_only_short: "mo titel", bodies: {"ZH": "Turitg", "BE": "Berna", "LU": "Lucerna", "UR": "Uri", "SZ": "Sviz", "OW": "Obwalden", "NW": "Nidwalden", "GL": "Glarus", "ZG": "Zug", "FR": "Friburg", "SO": "Solothurn", "BS": "Basilea-Citad", "BL": "Basilea-Champagna", "SH": "Schaffusa", "AR": "Appenzell Dadora", "AI": "Appenzell Dadens", "SG": "Son Gagl", "GR": "Grischun", "AG": "Argovia", "TG": "Turgovia", "TI": "Tessin", "VD": "Vad", "VS": "Vallais", "NE": "Neuchâtel", "GE": "Genevra", "JU": "Giura", "CHE": "Svizra"},
    g_aps: "Temas da standard (Année Politique Suisse)", r_note_stored: "Ils resultats ils pli novs tar il tema, zavrads tenor onn. La survista quinta tut ils fatgs tar il tema.", ov_head: "Survista", ov_line: "{n} fatgs en {p} parlaments", ov_line_one: "{n} fatgs en 1 parlament", ov_pool: "Tranter ils {k} fatgs ils pli adattads", ov_pool_topic: "Tranter ils {k} fatgs ils pli datiers dal tema", ov_hint: "Cliccai sin in parlament per restrenscher ils resultats.", ov_only: "Mo {b}", ov_all: "Tut ils parlaments", ov_closed: "«Erledigt ohne Angabe»: il parlament annunzia mo ch'il fatg è terminà, betg il resultat.",
    title: "Temas parlamentars", parl: "parlaments", topright: "Confederaziun · chantuns · citads · vischnancas", langs: "Lingua",
    h1a: "Temas", h1b: "parlamentars",
    lede: "Chattai fatgs (moziuns, dumondas e projects) da tut ils parlaments svizzers tenor tema, frasa u pled-clav, en mintga lingua naziunala.",
    footer: "Datas: OpenParlData.ch. Ils temas vegnan attribuids automaticamain; ina attribuziun sbagliada po vegnir annunziada.",
    federal: "Confederaziun", failed: "La tschertga n'è betg reussida. Empruvai pli tard anc ina giada.",
    s_num: "Tschertga", s_h2: "Da tge s'occupan ils parlaments?", s_placeholder: "Frasa u pled-clav, per exempel: vias da velo en la citad", s_go: "Tschertgar",
    f_topic: "Mo fatgs tar il tema", f_none: "Tut ils temas", f_level: "Nivel", f_from: "dapi l'onn", f_to: "fin l'onn",
    levels: {"all": "tut ils nivels", "country": "Confederaziun", "canton": "Chantun", "city": "Citad", "municipality": "Vischnanca"},
    g_adhoc: "Temas per tut ils parlaments", g_curia: "Secturs dal parlament federal", g_sg: "Secturs dal chantun Son Gagl",
    examples: ["intelligenza artifiziala en l'administraziun", "vias da velo", "abitaziuns a pretschs pajabels", "attaccas cibernetics sin ospitals"],
    r_count: "{n} resultats mussads per «{q}»", r_count_topic: "{n} resultats mussads per «{q}» en il tema «{t}»",
    r_none: "Nagins resultats.", r_loading: "Tschertga en lavur …",
    r_open: "Pagina originala", r_similar: "Fatgs sumegliants", r_type: "Gener", r_state: "Stadi", r_date: "Data",
    dym: "Manegiais Vus: «{q}»?", r_hint: "Tschertgai cun agens pleds, er en autras linguas naziunalas. In tema restrenscha ils resultats.",
    why: "Pertge", quote_hint: "Passadi proponì. Controllai el en il context.",
    verdict: {"yes": "Tema proponì", "likely": "Colliaziun pussaivla", "unsure": "malsegir", "no": "betg proponì"},
    t_head: "Temas da quest fatg", t_loading: "Ils temas vegnan determinads …", t_none: "Attribuì a nagin tema cun segirezza.",
    t_wrong: "laschar controllar", t_reported: "annunzià per la controlla", t_pick: "Tschertgar quest tema",
    flag: "«{t}» dubius? Dumandar ina controlla", flagged: "Grazia. L'attribuziun è notada per la controlla.",
    title_only: "Per quest fatg è disponibel mo il titel.",
    adhoc: {digitalisation: "Digitalisaziun"},
    r_count_browse: "{n} resultats mussads en il tema «{t}»",
    r_note_browse: "Resultats tschernids tar il tema, zavrads tenor onn. Cun in term da tschertga sa la glista vegnir restrenschida.",
    r_note_qt: "Mussads vegnan mo resultats attribuids al tema «{t}».",
    r_empty: "Endatai in term da tschertga u tschernai in tema.",
    r_loading_topic: "Tschertga en lavur, ils resultats vegnan attribuids al tema …",
    n_curia: "Ils secturs dal parlament federal valan mo per fatgs da la Confederaziun. Il nivel è perquai fixà sin «Confederaziun».",
    n_sg: "Ils secturs dal chantun Son Gagl valan mo per fatgs da quest chantun. La tschertga è perquai limitada al chantun Son Gagl.",
    n_years: "«Dapi l'onn» era suenter «fin l'onn». Ils dus onns èn vegnids barattads.",
    n_reset: "Il tema «{t}» na vala betg per quest nivel ed è vegnì allontanà.",
    r_none_qt: "Nagin dals {c} meglers resultats per «{q}» na tutga tar il tema «{t}».", r_none_topic: "Nagins fatgs tar il tema «{t}» n'èn vegnids chattads.",
    r_hint_qt: "Empruvai in auter term u laschai il champ da tschertga vid per vesair tut ils fatgs tar il tema.",
    canvas: ["Digitalisaziun", "Traffic", "Ambient", "Sanadad", "Migraziun", "Energia", "Furmaziun"],
  },
  en: {
    ov_show: "Show by parliament", ov_hide: "Hide parliaments",
    rv_mode: "Review mode", rv_login: "For reviewers", rv_name: "Name", rv_code: "Access code", rv_enter: "Sign in", rv_exit: "Leave review mode", rv_active: "Review mode: {n}", rv_bad: "The access code is wrong.", rv_queue: "Open reports", rv_none: "No open reports.", rv_yes: "Applies", rv_no: "Does not apply", rv_add: "Add a topic …", rv_saved: "saved", rv_failed: "Saving failed", rv_reviewed: "reviewed", rv_orig: "Original suggestion: {d}", rv_removed: "removed", rv_hint: "Your decision replaces the model's suggestion; the original suggestion stays stored.", rv_nostore: "No stored assignment exists for this topic yet.", rv_yesno_yes: "yes", rv_yesno_no: "no",
    listen: "Listen", listen_stop: "Stop reading", listen_loading: "Preparing …", listen_results: "Listen to the results", mic: "Speak your search", mic_stop: "Stop recording", mic_listening: "Speak now. Press the microphone again to finish.", mic_working: "Recognising your search …", mic_failed: "The recording did not work. Allow access to the microphone or type the search.",
    f_year: "Year", f_more: "More filters", f_less: "Fewer filters", ex_more: "More examples", f_body: "Parliament", f_body_all: "All parliaments", since2024: "Since 2024", r_sorted_rel: "sorted by relevance", r_sorted_year: "sorted by year", r_total: "{t} affairs on the topic in total", updating: "Updating results …", details_show: "Show details", details_hide: "Hide details", auto_check: "Automatic assignment, please check.", context_show: "Show context", context_hide: "Hide context", ev_loading: "Loading the passage …", ev_failed: "The passage could not be loaded.", retry: "Try again", flag_failed: "The report failed.", no: "No.", original: "Original: {l}", langnames: {"de": "German", "fr": "French", "it": "Italian", "rm": "Romansh", "en": "English"}, title_only_short: "title only", bodies: {"ZH": "Zurich", "BE": "Bern", "LU": "Lucerne", "UR": "Uri", "SZ": "Schwyz", "OW": "Obwalden", "NW": "Nidwalden", "GL": "Glarus", "ZG": "Zug", "FR": "Fribourg", "SO": "Solothurn", "BS": "Basel-Stadt", "BL": "Basel-Landschaft", "SH": "Schaffhausen", "AR": "Appenzell Ausserrhoden", "AI": "Appenzell Innerrhoden", "SG": "St. Gallen", "GR": "Graubünden", "AG": "Aargau", "TG": "Thurgau", "TI": "Ticino", "VD": "Vaud", "VS": "Valais", "NE": "Neuchâtel", "GE": "Geneva", "JU": "Jura", "CHE": "Switzerland"},
    g_aps: "Standard topics (Année Politique Suisse)", r_note_stored: "The newest matches for the topic, ordered by year. The overview counts all affairs on the topic.", ov_head: "Overview", ov_line: "{n} affairs in {p} parliaments", ov_line_one: "{n} affairs in 1 parliament", ov_pool: "Among the {k} best-matching affairs", ov_pool_topic: "Among the {k} affairs closest to the topic", ov_hint: "Click a parliament to limit the results to it.", ov_only: "Only {b}", ov_all: "All parliaments", ov_closed: "“Closed, outcome not stated” means the parliament reports only that the affair is closed, not how it ended.",
    title: "Parliament Topics", parl: "parliaments", topright: "Federal · cantons · cities · municipalities", langs: "Language",
    h1a: "Parliament", h1b: "topics",
    lede: "Find affairs (motions, questions and bills) from every Swiss parliament by topic, sentence or keyword, in any national language.",
    footer: "Data: OpenParlData.ch. Topics are assigned automatically; a wrong assignment can be reported.",
    federal: "Federal", failed: "The search failed. Please try again later.",
    s_num: "Search", s_h2: "What are the parliaments dealing with?", s_placeholder: "A sentence or a keyword, for example: cycle lanes in the city", s_go: "Search",
    f_topic: "Only affairs on the topic", f_none: "All topics", f_level: "Level", f_from: "from year", f_to: "to year",
    levels: {"all": "all levels", "country": "Federal", "canton": "Canton", "city": "City", "municipality": "Municipality"},
    g_adhoc: "Topics for all parliaments", g_curia: "Subject areas of the federal parliament", g_sg: "Subject areas of the Canton of St. Gallen",
    examples: ["AI in public administration", "cycle lanes and road safety", "affordable housing", "cyberattacks on hospitals"],
    r_count: "{n} results shown for “{q}”", r_count_topic: "{n} results shown for “{q}” in the topic “{t}”",
    r_none: "No results.", r_loading: "Searching …",
    r_open: "Original page", r_similar: "Similar affairs", r_type: "Type", r_state: "Status", r_date: "Date",
    dym: "Did you mean: “{q}”?", r_hint: "Search in your own words, in any national language. A topic narrows the results.",
    why: "Why", quote_hint: "Suggested passage. Please check it in context.",
    verdict: {"yes": "Topic suggested", "likely": "Possible link", "unsure": "uncertain", "no": "not suggested"},
    t_head: "Topics of this affair", t_loading: "Finding topics …", t_none: "No topic assigned with confidence.",
    t_wrong: "ask for review", t_reported: "sent for review", t_pick: "Search this topic",
    flag: "“{t}” doubtful? Ask for a review", flagged: "Thank you. The assignment is marked for review.",
    title_only: "Only the title of this affair is available.",
    adhoc: {digitalisation: "Digitalisation"},
    r_count_browse: "{n} results shown in the topic “{t}”",
    r_note_browse: "Selected matches for the topic, ordered by year. Add search terms to narrow the list.",
    r_note_qt: "Only results assigned to the topic “{t}” are shown.",
    r_empty: "Enter search terms or choose a topic.",
    r_loading_topic: "Searching and assigning the results to the topic …",
    n_curia: "The subject areas of the federal parliament apply to federal affairs only, so the level is set to “Federal”.",
    n_sg: "The subject areas of the Canton of St. Gallen apply to affairs of that canton only, so the search is limited to the Canton of St. Gallen.",
    n_years: "“From year” was later than “to year”. The two years were swapped.",
    n_reset: "The topic “{t}” does not apply to this level and was removed.",
    r_none_qt: "None of the {c} best matches for “{q}” belongs to the topic “{t}”.", r_none_topic: "No affairs were found on the topic “{t}”.",
    r_hint_qt: "Try other search terms, or leave the search field empty to see all affairs on the topic.",
    canvas: ["Digitalisation", "Transport", "Environment", "Health", "Migration", "Energy", "Education"],
  },
};
