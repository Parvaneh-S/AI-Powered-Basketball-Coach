"""Source-backed details for the existing coaching catalog.

Each row provides a topic, retrieval phrases, principle, explanation, use case,
limitation, and a ShotCoach application. Applications are coaching suggestions,
not claims that the cited source tested the exercise.
"""

SOURCES = {
    "setup": ("Jr. NBA — How to Shoot a Basketball", "https://jr.nba.com/shooting/"),
    "mechanics": ("USA Basketball — 7 Tips To Improve Your Shooting Mechanics", "https://www.usab.com/news/2014/01/7-tips-to-improve-your-shooting-mechanics"),
    "jump": ("Jr. NBA — How to Shoot a Jump Shot", "https://jr.nba.com/how-to-shoot-a-jump-shot/"),
    "basic_jump": ("USA Basketball — The Basic Jump shot", "https://www.usab.com/news/2023/05/the-basic-jump-shot"),
    "starter": ("Jr. NBA — Starter Practice Plans, shooting lesson", "https://jr.nba.com/basketball-practice-plans/starter/page/8/"),
    "rookie": ("Jr. NBA — Rookie Practice Plans, no-basket shooting lesson", "https://jr.nba.com/basketball-practice-plans/rookie/page/3/"),
    "step": ("Jr. NBA — Set Up Your Footwork Before Your Shot", "https://jr.nba.com/video/set-up-your-footwork-before-your-shot/"),
    "stop": ("Jr. NBA — Jump Stop Shooting Drill", "https://jr.nba.com/video/jump-stop-shooting-drill/"),
    "catch": ("Jr. NBA — Be Ready to Shoot Off the Catch", "https://jr.nba.com/video/be-ready-to-shoot-off-the-catch/"),
    "turn": ("Jr. NBA — Catch, Turn and Shoot Drill", "https://jr.nba.com/video/catch-turn-shoot-drill/"),
    "dribble": ("Jr. NBA — Learn to Shoot Off the Dribble", "https://jr.nba.com/video/learn-to-shoot-off-the-dribble/"),
    "fake": ("Jr. NBA — Fundamentals of the Shot Fake", "https://jr.nba.com/video/fundamentals-of-the-shot-fake/"),
    "fake_pullup": ("Jr. NBA — The Shot Fake 1-Dribble Pull-Up Drill", "https://jr.nba.com/video/the-shot-fake-1-dribble-pull-up-drill/"),
    "screen": ("Jr. NBA — Using a Screen Shooting Drill", "https://jr.nba.com/video/using-a-screen-shooting-drill/"),
    "selfpass": ("USA Basketball — Two-Hand Shooting From A Self-Pass", "https://www.usab.com/videos/2017/11/two-hand-shooting-from-a-self-pass"),
    "floater": ("USA Basketball — Shooting: 3 Part Floater", "https://www.usab.com/videos/2015/11/shooting-3-part-floater"),
    "spots": ("Jr. NBA — 7 Spot Shooting", "https://jr.nba.com/video/7-spot-shooting/"),
    "range": ("USA Basketball — 3 Ways to Make More 3-Point Shots", "https://www.usab.com/news/2014/01/3-ways-to-make-more-3-point-shots"),
    "allen": ("USA Basketball — Ray Allen's Pregame Shooting Routine", "https://www.usab.com/news/2014/01/ray-allens-pregame-shooting-routine"),
    "routine": ("Jr. NBA — Fundamentals of the Free Throw", "https://jr.nba.com/video/fundamentals-of-the-free-throw/"),
    "routine_review": ("Rupprecht, Tran and Gröpel — Pre-performance routines meta-analysis", "https://doi.org/10.1080/1750984X.2021.1944271"),
    "release_study": ("Slegers, Lee and Wong — Release variability and shooting performance", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8256521/"),
    "pro_distance": ("Cabarkapa et al. — Distance and proficiency in professional male shooters", "https://pmc.ncbi.nlm.nih.gov/articles/PMC9590067/"),
    "female_distance": ("Cabarkapa et al. — Kinematic differences in female shooters", "https://pmc.ncbi.nlm.nih.gov/articles/PMC10531893/"),
    "free_throw_study": ("Cabarkapa et al. — Markerless analysis of free throws", "https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2023.1208915/full"),
    "coordination": ("Mullineaux and Uhl — Free-throw coordination and kinematics", "https://pubmed.ncbi.nlm.nih.gov/20552519/"),
    "spin": ("Slegers et al. — Backspin alignment and variability", "https://www.tandfonline.com/doi/pdf/10.1080/02640414.2022.2080164"),
    "contest": ("van Maarseveen and Oudejans — Contested and uncontested jump shots", "https://pmc.ncbi.nlm.nih.gov/articles/PMC5961512/"),
    "fatigue": ("Li et al. — Fatigue and shooting accuracy meta-analysis", "https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2025.1435810/full"),
    "sprints": ("Slawinski et al. — Repeated sprints and three-point kinematics", "https://pmc.ncbi.nlm.nih.gov/articles/PMC6006537/"),
    "transfer": ("Czyż et al. — Contextual interference and transfer review", "https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2024.1377122/full"),
    "focus": ("Chua et al. — Attentional focus meta-analyses", "https://pubmed.ncbi.nlm.nih.gov/34843301/"),
    "focus_bias": ("McKay et al. — Reappraisal of external attentional focus", "https://pubmed.ncbi.nlm.nih.gov/39480294/"),
    "children": ("van der Veer et al. — Instructions and feedback in children", "https://pubmed.ncbi.nlm.nih.gov/36007080/"),
    "warmup": ("Davis et al. — Neuromuscular warm-ups in basketball", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8446130/"),
    "youth": ("NBA and USA Basketball — Youth Basketball Guidelines", "https://www.usab.com/play/youth-basketball-guidelines"),
    "pain": ("NHS — Shoulder pain", "https://www.nhs.uk/symptoms/shoulder-pain/"),
}

LIBRARY = {}


def add(source, basis, rows):
    attribution, url = SOURCES[source]
    for key, parent, title, phrases, principle, explanation, use, limits, application in rows:
        if key in LIBRARY:
            raise ValueError(f"Duplicate knowledge ID: {key}")
        LIBRARY[key] = dict(
            topic=title, parent=parent, phrases=tuple(phrases.split("|")), keywords=(),
            principle=principle, purpose=explanation, use_when=use, avoid_when=limits,
            application=application, evidence_basis=basis, source=attribution, url=url,
            cue=None, exercise=None, progression=None, evaluation=None, metric=None,
        )


add("mechanics", "coaching_guidance", [
    ("open_stance", "stance", "Open or square stance", "open stance|square stance|feet turned out|feet point sideways",
     "A slightly open stance and a squarer stance are both starting options.",
     "The foot angle changes how the body faces the basket and may change how comfortably the shooting arm lifts.",
     "When comparing two comfortable stationary setups.", "Foot angle alone cannot identify a fault.",
     "Compare a few shots in each comfortable stance from one spot and keep the setup you can repeat."),
    ("staggered_feet", "stance", "Staggered starting feet", "staggered feet|shooting foot forward|one foot ahead",
     "A small stagger can be a useful stationary starting position.",
     "The shooting-side foot can sit a little forward if the player feels balanced as the ball rises.",
     "When an even stance feels awkward.", "The amount of stagger is a comfort choice.",
     "Reset the same small stagger for a close set and check whether you can rise without shifting."),
    ("stable_base", "stance", "Stable base before the lift", "wobble before release|rocking on my feet|unstable base|weight uneven",
     "Check stability at the start of the lift before adjusting the release.",
     "A consistent base gives you a reference for deciding whether the wobble happens before or after the ball starts up.",
     "When a stationary setup feels unstable.", "A deliberate move into the shot can involve weight transfer.",
     "Film a close set with both feet visible and compare the start of the lift."),
    ("grip_pressure", "preparation", "Grip pressure", "grip pressure|gripping too hard|squeeze the ball|palm gap",
     "Use enough grip to control the ball while keeping the hand relaxed.",
     "The fingers help support and guide the ball during the lift.",
     "When the player reports a tense grip.", "Hand size and ball size affect how the ball rests in the hand.",
     "Try a few unhurried close shots with a relaxed grip and note whether control stays steady."),
    ("target_choices", "release", "Choosing a rim target", "front of the rim|back of the rim|aim spot|where should i aim",
     "Choose a visible rim target you can use consistently.",
     "A repeatable visual target gives the player one less decision during setup.",
     "When aim shifts between attempts.", "The best target can vary by player or shot type.",
     "Use one chosen rim target for a set before judging whether it helps."),
    ("soft_finish", "finish", "Relaxed finish", "relaxed wrist finish|stiff follow through|tense finish",
     "Use a relaxed finish as a comfort cue.",
     "Letting the arm finish without forcing the wrist gives the player a motion they can try to repeat.",
     "When the player reports tightening up near release.", "A still image cannot show how much force or tension the player used.",
     "Compare a short close set with the relaxed-finish cue against your usual shot."),
    ("one_rise", "timing", "Coordinating the rise and lift", "rise together|legs then arms|connect my legs|sequence legs and arms",
     "Experiment with starting the ball lift as the body rises.",
     "The cue connects lower-body movement to the arm delivery so the two parts feel less disconnected.",
     "When the player reports a pause between loading and lifting.", "The timing can vary with distance and shot type.",
     "Start close and review whether the lift and rise look consistent across repetitions."),
])

add("setup", "coaching_guidance", [
    ("guide_hand_job", "preparation", "Guide-hand support", "guide hand pushes|guide hand separation|off hand pushing|two handed push",
     "Give the guide hand a support role during the lift.",
     "A close-range rehearsal can help a player feel the difference between steadying the ball and propelling it.",
     "When the player reports using the guide hand to push.", "Ball flight alone cannot establish which hand pushed.",
     "Rehearse a comfortable lift with the guide hand lightly supporting the side, then try a close set."),
    ("one_hand_isolation", "arm", "One-hand form rehearsal", "one hand form shooting|shoot with one hand|one handed rehearsal",
     "Use short one-hand rehearsals to isolate the shooting hand.",
     "Removing the guide hand briefly lets the player focus on the delivery from a very comfortable spot.",
     "When learning how the shooting hand supports the ball.", "Treat it as an exercise; the normal shot can keep the guide hand.",
     "Rehearse close, then return to your usual two-hand setup and compare the feel of the lift."),
    ("finger_contact", "release", "Fingertip delivery", "fingertip release|last finger|middle finger release|ball rolls off",
     "Use fingertip delivery as a feel cue during easy shots.",
     "The last moments of contact are brief and can be hard to see in a normal clip.",
     "When the player asks about hand contact at release.", "There is no need to force a specific last finger from an unclear view.",
     "Try an easy close set and compare comfort and ball control without chasing a specific finger."),
    ("forearm_support", "arm", "Forearm support during delivery", "forearm under the ball|forearm vertical|forearm be vertical|forearm alignment",
     "Use the forearm as a reference for how the shooting hand supports the ball.",
     "A comfortable hand-under-ball position can help the player feel how the ball is supported before extension.",
     "When evaluating ball support in the stationary lift.", "A projected elbow angle cannot establish the forearm’s depth or alignment with the rim.",
     "Compare straight-on and side views of a slow lift before drawing conclusions about alignment."),
    ("close_first", "mechanics", "Close-range start", "beginner shooting progression|learning to shoot from scratch|close form shooting",
     "Start somewhere the ball reaches the rim comfortably.",
     "A short distance lets a learner try one motion cue with less demand for range.",
     "When introducing a new shot or returning to fundamentals.", "Close-range success alone does not establish transfer to game shots.",
     "Build a short repeatable set close to the rim, then retest after a small step back."),
])

add("starter", "coaching_guidance", [
    ("step_in", "stance", "Step-in catch-and-shoot", "step in shooting|partner step in|step into the catch|one two step into shot",
     "Rehearse the footwork and catch together.",
     "A partner pass gives the player a consistent cue for stepping into a stable shooting base.",
     "When feet arrive late on a pass.", "Match pass location and pace when comparing footwork options.",
     "Use a partner and one receiving spot. Compare whether you are balanced immediately after the catch."),
    ("line_drive_knee_arm", "timing", "Coordinated knee and arm extension", "knee and arm extension|extend knees and arm|legs and elbow together",
     "Use close form shots to feel the knees and shooting arm extend in one delivery.",
     "The two-hand drill links a comfortable load to the arm motion as the ball goes up.",
     "When lower-body and arm actions feel disconnected on an easy shot.",
     "The drill is a coaching cue; a side view cannot quantify interjoint forces.",
     "Compare the beginning of the rise and the estimated release in a short matched set."),
    ("hold_finish", "finish", "Holding the finish in practice", "hold my follow through|hold the finish|follow through duration",
     "A brief voluntary hold can make the finish easier to review.",
     "Holding the shape gives the player a stationary moment to notice where the arm ended up.",
     "In a comfortable stationary close-range rehearsal.", "An early post-release frame cannot establish how long a player held the finish.",
     "Film through the end of the motion and use the hold as a check rather than an accuracy goal."),
    ("bank_target", "bank", "Backboard target from one spot", "where to aim off glass|bank shot target|backboard square aim",
     "Practise the board target from a fixed position before moving.",
     "Changing position changes where the ball needs to contact the board.",
     "When learning an angled bank shot.", "The target changes with location and ball path.",
     "Pick one close spot and record board contact and outcome separately."),
])

add("pro_distance", "observational_study", [
    ("hip_loading", "knees", "Hip loading with distance", "hip bend|hip loading|hip flexion on threes|bend at hips",
     "Hip and knee loading can change as shooting distance changes.",
     "In one professional men's sample, longer shots showed a different preparatory configuration involving the hip, knee, and elbow height.",
     "When the player's long-range setup looks different from their free throw.",
     "Group averages do not prescribe a hip angle or prove the cause of a miss.",
     "Compare the loading phase within each distance before testing a cue."),
    ("knee_dip_depth", "knees", "Choosing a comfortable knee dip", "dip too deep|how much knee bend|how deep should i dip|deeper knee bend",
     "Treat knee-dip depth as specific to the player and shooting task.",
     "The loading seen in professional long-range attempts can differ from the loading in shorter shots.",
     "When deciding whether to test a bigger or smaller dip.", "Depth alone says little about timing, power or whether a change helps.",
     "Compare only matched-distance attempts and record both comfort and outcomes."),
    ("three_point_loading", "distance", "Three-point preparation", "three point mechanics|three pointer mechanics|three point loading|lean on threes",
     "Expect some adaptation in the setup for longer shots.",
     "Professional men in one study showed different preparatory mechanics in threes than in free throws and twos.",
     "When an efficient short-range shot changes beyond the arc.", "Differences across shot types cannot establish deterioration.",
     "Create separate baselines for threes and closer shots."),
    ("release_height", "release", "Release height as a separate variable", "release height|low release against defenders|high release point",
     "Release height describes where the ball leaves the hand.",
     "Body position, arm elevation, and any vertical rise can all affect that location.",
     "When discussing how high a jump shot leaves the hand.", "A high-looking elbow in one view is not a ball-release height measurement.",
     "Compare the same estimated release phase from a stable view and describe visible position qualitatively."),
    ("set_point_height", "preparation", "Set point and release height", "set point height|low set point|ball above forehead",
     "Separate where the ball is prepared from where it is released.",
     "Preparatory elbow height can vary with the task while the final ball position depends on later movement.",
     "When a player compares a low setup with a high-looking finish.", "A difference in set point alone does not establish an advantage.",
     "Review one setup frame and one release frame from each matched attempt."),
])

add("female_distance", "observational_study", [
    ("midrange_mechanics", "mechanics", "Mid-range jump-shot mechanics", "mid range mechanics|two point jump shot|midrange jumper setup",
     "Evaluate mid-range mechanics on matched mid-range attempts.",
     "A sample of female players showed proficiency-related differences in preparation and release for twos and a different pattern for threes.",
     "When reviewing a player's mid-range jumper.", "These group comparisons are task- and sample-specific.",
     "Film matched attempts from one mid-range location and separate setup features from outcomes."),
    ("shoulder_elevation", "arm", "Shoulder elevation in the lift", "shoulder flexion|shoulder elevation|upper arm lift|shoulder angle at release",
     "The shoulder and elbow describe different parts of the delivery.",
     "Preparatory shoulder position can differ among groups of shooters and across tasks.",
     "When a player asks what the upper arm is doing during the lift.", "An apparent angle in a clip cannot establish shoulder mobility or joint load.",
     "Compare the upper arm in the same phase using matched views before choosing a cue."),
    ("sample_specific_form", "individual", "Proficiency findings depend on the sample", "men versus women shooting form|female shooting mechanics|do all good shooters move alike",
     "Treat proficiency findings as examples of how a group solved a task.",
     "Studies of different player groups or shot distances report different patterns of joint and release variables.",
     "When deciding whether a published result transfers to an individual.", "A group finding is not a criterion for how one player must move.",
     "Choose comparable footage of your own comfortable shot as the baseline."),
])

add("free_throw_study", "observational_study", [
    ("free_throw_load_control", "knees", "Controlled free-throw loading", "free throw leg speed|rushing my free throw dip|controlled free throw",
     "Consider how quickly the player loads and rises as well as how far the knees bend.",
     "A markerless free-throw study found slower knee and body movement on average in its proficient group.",
     "When stationary foul shots feel hurried.", "That group difference does not set a universal tempo or reveal the cause for one player.",
     "Compare your comfortable pace against a slightly calmer setup without changing the other cues."),
    ("free_throw_jump_comparison", "mechanics", "Free throws and jump shots solve different tasks", "free throw vs jump shot|set shot versus jump shot|jump on free throws",
     "Keep stationary free throws and jump shots in separate technique comparisons.",
     "A free throw is uncontested and has a fixed starting distance, while a jump shot may respond to movement or a defender.",
     "When someone copies a jump-shot technique straight into foul shooting.", "A jump can be part of some players’ free-throw technique.",
     "Use a separate baseline and routine for each shot type."),
    ("between_vs_within", "individual", "Between-player and within-player comparisons", "group averages|proficient shooters versus me|group differences apply to me",
     "Compare the player's own repetitions before applying a group result.",
     "A group contrast between proficient and less proficient shooters answers a different question from a make–miss contrast within one shooter.",
     "When interpreting a research result alongside player footage.",
     "Neither comparison by itself proves the benefit of a technique change.",
     "Use the published observation to choose what to inspect, then examine matched attempts from the player."),
])

add("coordination", "observational_study", [
    ("elbow_wrist_sequence", "release", "Elbow–wrist coordination close to release", "elbow wrist coordination|wrist timing|elbow and wrist sequence|wrist fires too early",
     "The elbow and wrist can contribute as a coordinated movement close to release.",
     "One collegiate free-throw study found a difference in late elbow–wrist coordination variability between misses and swishes.",
     "When asking how these joints can work together.", "The study's instrumentation and timing resolution exceed what ordinary clips establish.",
     "Review the full visible delivery and describe uncertainty before testing a small timing cue."),
    ("wrist_speed_evidence", "release", "Wrist speed and ball outcome", "wrist speed|fast wrist snap|quick wrist snap|snap wrist harder",
     "A quicker-looking wrist action alone offers weak evidence about the ball release.",
     "In a free-throw study comparing swishes and misses, wrist linear velocity did not distinguish the groups.",
     "When a player wants to snap harder after missing short.", "This does not rule out relevant wrist differences for a particular shooter.",
     "Check the ball path and comparable attempts before changing the wrist cue."),
    ("individual_coordination", "individual", "Individual coordination patterns", "unusual elbow wrist pattern|joint coordination differences|different shooting styles",
     "Different players can organize the joints differently while delivering an effective shot.",
     "Within-player coordination can be more informative than comparing appearance across players.",
     "When the main concern is that one player's motion looks unlike someone else's.", "Comfort and outcomes matter, and short clips describe only a small sample.",
     "Review the player's own repeatability and outcomes before considering any visual change."),
])

add("release_study", "observational_study", [
    ("distance_release_speed", "distance", "Distance and ball release speed", "release velocity|ball speed for range|release speed for threes|how hard to shoot farther",
     "Longer shots can require a faster ball release.",
     "In a small study, average release speed rose from free throws to threes alongside changes in lower-body movement.",
     "When comparing how the ball reaches a nearer and farther target.", "An elbow angle or image-plane trajectory does not measure speed, force or power.",
     "Build the comfortable closer shot first and compare separate sets at each distance."),
    ("power_vs_speed", "distance", "Power versus visible speed", "measure shooting power|joint angle power|calculate force|how much force",
     "Distinguish ball motion from force and power produced by the player.",
     "A ball release estimate describes the ball. The forces and contributions of individual joints require different evidence.",
     "When a player wants a power diagnosis from ordinary footage.",
     "ShotCoach pose angles cannot identify joint force or actual mechanical power.",
     "Ask where the ball tends to arrive at one repeatable distance and look for a trial the player can compare."),
    ("same_distance_variability", "distance", "Match distance before comparing variability", "same distance before comparing|compare range with consistency|different distances consistency",
     "Measure repeatability separately at each distance.",
     "The release conditions that move the ball to a farther target can differ even if the shooter controls each condition consistently.",
     "When a log contains both free throws and threes.", "Pooling the distances can mistake intentional changes for inconsistency.",
     "Log each shooting distance as its own set and compare like with like."),
    ("speed_variability_vs_arc", "distance", "Release-speed consistency and arc", "speed variability|release angle variability|consistent arc but missing",
     "Different ball-release variables can relate differently to outcomes.",
     "In one small study, release-speed variability tracked performance more closely than release-angle variability.",
     "When interpreting why a consistent-looking arc can coexist with misses.",
     "The study used model-estimated release quantities and does not prove a cause for a specific player.",
     "Keep separate notes on visible flight and outcomes instead of diagnosing from arc alone."),
    ("accuracy_vs_repeatability", "individual", "Accuracy and movement repeatability", "consistent form but miss|accuracy versus consistency|repeatable but inaccurate|mechanical consistency versus makes",
     "Score outcomes separately from how repeatable a movement appears.",
     "A narrow joint-angle spread describes one movement feature; the ball still has multiple release variables that affect the result.",
     "When shooting results and measured form tell different stories.", "A few attempts can produce an unstable make rate or spread.",
     "Compare known makes and measured spread side by side in matched sets."),
    ("launch_vs_entry", "distance", "Launch angle and rim-entry angle", "entry angle versus launch|launch vs entry|ball entry angle|angle at the rim",
     "The launch angle is at release. The entry angle is the ball's direction near the rim.",
     "The flight changes between those points, so a visible elbow angle cannot serve as either ball angle.",
     "When someone asks about trajectory or a steep entry.", "Inferring either angle requires suitable ball tracking and camera calibration.",
     "Describe what is visible about the flight without assigning an angle from ordinary footage."),
    ("arc_tradeoff", "distance", "Arc and release trade-offs", "higher arc always better|too much arc|flat trajectory|ideal shot arc",
     "Treat arc, release height and speed as interacting parts of the flight.",
     "Several combinations can reach the rim. Changing arc can also change the speed needed at the same distance.",
     "When a player wants a universal arc target.", "A single view or a single miss does not identify an optimal trajectory.",
     "Test one comfortable flight cue from the same distance and compare where the shots arrive."),
])

add("spin", "observational_study", [
    ("spin_axis", "release", "Spin axis versus spin rate", "spin axis|spin rate|backspin alignment|spin rpm",
     "The direction of the spin axis and the speed of rotation are separate variables.",
     "A ball can rotate quickly while the axis is tilted, so a rotation count does not describe alignment.",
     "When reviewing visible ball rotation.", "Ordinary footage may make the seams and spin axis difficult to resolve.",
     "Look for a visible seam over successive frames before describing any rotation qualitatively."),
    ("backspin_repeatability", "release", "Repeatable backspin", "how much backspin|more backspin|backspin consistency|perfect rotation",
     "Start by reviewing repeatability rather than trying to maximize spin.",
     "Direct backspin research treats rotation as one of several quantities describing the release.",
     "When a player wants to add spin to every shot.", "No spin target is established for an individual from these clips.",
     "Use a close set and note whether the release feels repeatable and the ball arrives consistently."),
])

add("spin", "coaching_hypothesis", [
    ("side_spin_hypothesis", "release", "When the ball appears to spin sideways", "sidespin|side spin|sideways rotation|ball spins sideways",
     "A tilted-looking spin can prompt a closer look at delivery.",
     "Study measurements separated axis alignment from consistency. A single camera and ball image can make those quantities hard to distinguish.",
     "When rotation repeatedly looks tilted in clear footage.",
     "Side spin does not identify the responsible finger, wrist or guide hand.",
     "Review several clearly visible releases before testing one light hand-support cue."),
])

add("jump", "coaching_hypothesis", [
    ("short_miss", "distance", "Investigating repeated short misses", "miss short|shots keep falling short|front rim misses|short on every shot",
     "Repeated short arrivals are a reason to isolate distance and delivery.",
     "Possible contributors include starting too far away for the current rhythm, rushing the lift, or changing the ball path.",
     "When the player repeatedly sees the ball arrive short.", "Front-rim contact does not identify the responsible joint or prove a power deficit.",
     "Compare a closer set with the usual set while keeping the cue and recording angle the same."),
    ("long_miss", "distance", "Investigating repeated long misses", "miss long|back rim misses|overshooting the rim|shots go long",
     "Check whether long arrivals persist from the same spot.",
     "Range, pace, and trajectory can interact. A long result gives a direction to investigate.",
     "When back-rim or long misses recur.", "One long miss does not establish excessive force.",
     "Log short and long results from a fixed spot before testing any delivery change."),
    ("lateral_miss", "arm", "Investigating left and right misses", "misses left|missing right|left right misses|ball drifts sideways",
     "Treat repeated lateral misses as an observation about the ball path.",
     "Target alignment, feet, ball delivery and camera perspective are separate questions.",
     "When the player identifies a repeating side miss from one location.", "The direction alone cannot show whether the elbow or guide hand is responsible.",
     "Use a stable front or rear view and compare same-spot attempts before changing a cue."),
    ("drift_vs_landing", "landing", "Intended drift versus loss of balance", "drift on landing|forward drift|land forward|leaning jump shot",
     "Judge landing relative to the intended shot.",
     "A stationary jumper and a moving pull-up start with different momentum.",
     "When the player is worried that they do not land on the exact takeoff spot.",
     "A clipped landing cannot establish balance or the cause of a missed shot.",
     "Film the feet before takeoff and through landing, comparing stationary shots with stationary shots."),
])

add("routine", "coaching_guidance", [
    ("foul_line_sequence", "routine", "Free-throw routine sequence", "free throw routine steps|foul line sequence|how many dribbles before a free throw",
     "Choose a short sequence that reliably gets you ready to shoot.",
     "The sequence might include settling the feet, a chosen rhythm and a consistent target.",
     "When free throws feel improvised or rushed.", "The number of dribbles is a personal choice within the rules.",
     "Pick a sequence you can repeat comfortably for a matched set."),
    ("routine_reset", "routine", "Resetting after a missed free throw", "reset after missed free throw|reset after a missed free throw|missed first free throw|reset at foul line",
     "Return to the normal preparation after a miss.",
     "A familiar reset gives the next attempt the same starting decisions without immediately adding a mechanical cue.",
     "Between consecutive free throws.", "Repeated problems deserve later review; one miss is too little to justify a form change.",
     "Practice using the same reset after both makes and misses."),
])

add("routine_review", "research_review", [
    ("routine_pressure", "routine", "Rehearsing a routine under pressure", "pressure free throws|nervous at foul line|preshot routine under pressure",
     "Rehearse the usual routine under mild, relevant pressure.",
     "A cross-sport review found benefits from pre-performance routines under both low and pressured conditions.",
     "When a comfortable routine tends to disappear with a score or audience.",
     "The review pooled different sports and does not prescribe a single routine.",
     "Use the familiar sequence first, then add a simple scoring target in a separate set."),
    ("routine_flexibility", "individual", "Personalizing a pre-shot routine", "copy somebody else routine|same routine everyone|routine duration",
     "Keep the elements of a routine that prepare the player for the task.",
     "Pre-performance routines can include both actions and thoughts, with many ways to arrange them.",
     "When adapting an example to your own foul shooting.", "Length or appearance alone does not establish a useful routine.",
     "Keep the useful preparation steps and compare comfort when you simplify an unnecessary step."),
])

add("step", "coaching_guidance", [
    ("one_two_footwork", "stance", "One-two footwork", "one two footwork|one two step|one two stop|step foot order",
     "Practice the one-two step as a way to organize the base before the shot.",
     "The two contacts give the player a consistent sequence to rehearse before adding a faster pass.",
     "When learning to step into a catch.", "Approach direction changes which sequence feels natural.",
     "Start without a shot, then add an easy pass while keeping the receiving location fixed."),
])

add("stop", "coaching_guidance", [
    ("jump_stop_base", "stance", "Jump stop into the shot", "jump stop shooting|hop into the shot|two foot stop",
     "Use a comfortable two-foot stop when practicing balance out of motion.",
     "A repeatable stop gives the player time to organize the lift.",
     "When arriving off balance from an approach.", "A jump stop and a one-two step are both practice options.",
     "Rehearse each from the same approach direction before deciding which to use."),
])

add("catch", "coaching_guidance", [
    ("catch_ready", "preparation", "Getting ready before the catch", "ready before the pass|shoot off the catch|catch and shoot|hands ready",
     "Prepare to receive the ball before it reaches you.",
     "Organizing the feet and hands early leaves less setup to do after the catch.",
     "When a catch-and-shoot attempt feels rushed.", "A misplaced pass can still require time to reset.",
     "Use predictable partner passes and check which part of the setup can happen earlier."),
    ("rushed_catch", "timing", "Diagnosing a rushed catch", "rush after the catch|slow catch release|late preparation off the catch",
     "Separate the receiving action from the delivery when a catch feels rushed.",
     "Pass quality or late foot preparation can account for time before the release begins.",
     "When comparing quickness from the catch.", "Total catch-to-release time cannot locate the delay by itself.",
     "Compare clips with similarly placed passes and mark the catch, foot plant and release."),
])

add("turn", "coaching_guidance", [
    ("turn_balance", "stance", "Balance when catching and turning", "catch turn and shoot|turn to square|turning jumper balance",
     "Use the turn to arrive in a controllable shooting base.",
     "Adding rotation makes the base harder to organize than on a stationary shot.",
     "When practicing a catch with the body turned away from the basket.",
     "The drill does not set a universally correct foot angle.",
     "Begin with a small turn and increase it after the base stays comfortable."),
])

add("selfpass", "coaching_guidance", [
    ("self_pass_transfer", "preparation", "Self-pass progression", "self pass shooting|toss to myself|solo catch and shoot",
     "Use a self-pass to add a catch without requiring a partner.",
     "A small toss creates a receiving task between stationary form work and variable partner passes.",
     "When practicing alone with a ball and hoop.", "A self-pass is more predictable than a pass in a game.",
     "Alternate a stationary set and a self-pass set from one comfortable distance."),
])

add("dribble", "coaching_guidance", [
    ("pullup_gather", "timing", "Gathering for a pull-up", "pull up jumper|shoot off the dribble|dribble gather|one dribble pull up",
     "Practice slowing into a controlled gather before adding shooting speed.",
     "The last bounce, step and lift have to fit together in a moving shot.",
     "When learning a pull-up or arriving hurried after the last dribble.",
     "Match the approach direction when comparing attempts.",
     "Begin with one controlled dribble and mark a spot where the gather starts."),
])

add("fake", "coaching_guidance", [
    ("shot_fake_balance", "stance", "Staying balanced through a shot fake", "shot fake balance|pump fake footwork|sell the shot fake",
     "Make the fake resemble the start of the shot while keeping a base for the next action.",
     "The fake is useful when it creates a decision or space without requiring an immediate shot.",
     "When a player loses balance on a shot fake.", "A fake works in response to the defender, so faking every catch is unnecessary.",
     "Start with a fake and reset, then add a partner who sometimes contests."),
])

add("fake_pullup", "coaching_guidance", [
    ("fake_to_pullup", "timing", "Linking a shot fake to a pull-up", "pump fake one dribble|fake to pull up|shot fake and pull up",
     "Learn the fake and pull-up separately before combining them.",
     "Practicing the transition helps the player arrive at the second shot on balance.",
     "When a closing defender takes away the original shot.", "A hurried pull-up may be a poorer choice than passing or resetting.",
     "Build the fake, one controlled dribble and balanced gather into an unopposed rehearsal."),
])

add("screen", "coaching_guidance", [
    ("screen_shooting", "stance", "Shooting after using a screen", "shoot off a screen|screen shooting drill|get around a screen",
     "Practice the route and receiving footwork together.",
     "The path around the screen determines how much time and balance the shooter has on the catch.",
     "When a player is comfortable shooting on stationary passes.", "An unopposed route drill cannot teach every defensive read.",
     "Repeat the same route at a comfortable speed, then add a passer and vary the timing."),
])

add("floater", "coaching_guidance", [
    ("floater_touch", "release", "Practicing floater touch", "floater touch|three part floater|runner over a defender",
     "Give the floater a separate practice set from your jump shot.",
     "Its moving approach and touch place different demands on the delivery.",
     "When learning a short shot over a defender.", "A set-shot angle or finish target does not transfer directly.",
     "Start near the basket with a controlled approach and compare arrivals before adding a defender."),
])

add("basic_jump", "coaching_guidance", [
    ("release_jump_timing", "timing", "Release relative to the jump", "release at apex|top of my jump|release while rising|jump release timing",
     "Treat release timing relative to the jump as a cue to test.",
     "A coordinated delivery can use the rise to help move the ball toward the target.",
     "When a player feels they hang before releasing or wants more comfortable range.",
     "Different shots and players can use different release timings.",
     "Film a same-spot set and compare the release phase with the player's normal rise."),
    ("range_limit", "distance", "Recognizing a comfortable range limit", "force it from deep|too far from the hoop|comfortable range limit",
     "Use the appearance of forcing the shot as a reason to check the practice distance.",
     "A step closer can let the player keep their familiar delivery while testing a range issue.",
     "When deeper shots feel strained.", "A self-reported range limit can shift with equipment, fatigue and experience.",
     "Mark the farthest comfortable spot and use a slightly closer location for the next controlled set."),
])

add("range", "coaching_guidance", [
    ("range_ladder", "distance", "Stepping back to build range", "distance ladder|range ladder|step back after makes|increase three point range|building three point range",
     "Extend practice range in small steps from a comfortable starting spot.",
     "Separating distances lets the player see where delivery starts to change.",
     "When learning to reach the three-point line comfortably.", "A make at one distance is too little evidence to move back every time.",
     "Use a short set at each spot and step in again if you have to force the ball."),
    ("three_point_stationary_transfer", "distance", "Moving from stationary threes to game threes", "game speed threes|practice threes off a pass|transfer three pointers to games",
     "Build a comfortable stationary three before adding a receiving or movement demand.",
     "A pass or step-in changes how the player prepares for the shot.",
     "When stationary threes improve but game attempts still feel rushed.",
     "An isolated range drill cannot establish game transfer.",
     "Compare stationary and step-in sets separately from the same three-point spot."),
])

add("spots", "coaching_guidance", [
    ("spot_map", "routine", "Tracking shooting by court location", "spot shooting|seven spot|which spot should i practice|corner versus wing",
     "Keep a separate attempt count for each shooting spot.",
     "Location-specific sets can show where a player feels ready or needs more practice.",
     "When comparing the corner, wing and top.", "Unequal attempt counts and mixed distances can mislead.",
     "Use a similar small set at each spot and log both attempts and makes."),
    ("midrange_spots", "mechanics", "Mid-range spot practice", "mid range spots|practice midrange|mid range by court location",
     "Pick one mid-range location before changing the approach.",
     "A fixed location makes it easier to compare a stationary shot with a step-in or pull-up.",
     "When a player wants an actionable mid-range baseline.",
     "The resulting make rate applies to that location and task.",
     "Record matched sets from one mid-range spot, separating stationary attempts from moving ones."),
])

add("allen", "coaching_guidance", [
    ("advanced_routine", "routine", "Advanced pregame routine", "ray allen routine|pregame shooting plan|advanced warmup shooting",
     "Use a familiar progression across spots and distances.",
     "Ray Allen's reported warm-up illustrates how an experienced player can organize repeated game-like preparations.",
     "When designing a personal pregame sequence after basics are stable.",
     "A professional player's volume is an example rather than a workload target.",
     "Borrow the progression order and select a workload that fits your own warm-up."),
])

add("contest", "observational_study", [
    ("open_vs_contested", "individual", "Open versus contested shooting", "contested versus open|defender changes my shot|open shots in practice",
     "Assess open and contested attempts separately.",
     "An approaching defender changed execution and gaze in a youth study even though accuracy responses varied across players.",
     "When a player's game shot looks unlike practice.", "The defender changes the task, so altered mechanics can be adaptive.",
     "Compare open sets with sets grouped by a consistent level of contest."),
    ("representative_practice", "routine", "Adding a defender to advanced practice", "representative practice|practice with closeouts|add passive defender|defender decision drill",
     "Add a realistic read after the comfortable pattern is established.",
     "A controlled closeout introduces a timing and decision problem missing from unopposed attempts.",
     "When an experienced player wants better transfer to games.", "A contested practice result should not be compared directly to an open-set make rate.",
     "Use an agreed passive closeout first and count sound shoot-or-pass decisions as well as makes."),
    ("gaze_under_contest", "release", "Target attention under a closeout", "lose sight of rim|watch the defender instead of rim|gaze under pressure",
     "Check what the player attends to as the defender approaches.",
     "Contested shooting can alter where and when players look before releasing.",
     "When target attention feels disrupted in games.", "A side-view clip cannot measure fixation or prove the reason for a miss.",
     "Compare a comfortable open set with a controlled closeout and ask where attention went."),
])

add("transfer", "research_review", [
    ("blocked_practice", "routine", "Blocked practice for a new movement", "blocked practice|same shot in a block|same spot first",
     "Use repeated attempts in one condition when first learning a cue.",
     "A simple block gives the player time to understand the task before introducing switching demands.",
     "When the movement or cue is new.", "A good practice block alone does not establish retention or transfer.",
     "Use one short block, then retest under the same conditions at a later practice."),
    ("variable_practice", "routine", "Varying practice for transfer", "random practice|variable practice|mix shooting spots|alternate locations",
     "Mix locations or preparations after the basic task is familiar.",
     "Switching between attempts can test whether the skill transfers, though review findings vary by setting.",
     "When a player is comfortable in a fixed practice block.",
     "A lower make count in a harder mixed set does not necessarily mean learning declined.",
     "Keep a fixed baseline and track the mixed set separately."),
    ("retention_test", "routine", "Checking whether practice stuck", "retention test|did learning stick|retention versus practice performance|next day test",
     "Retest later using a comparable set.",
     "Performance during coached practice and the ability to reproduce it later are different outcomes.",
     "When a cue seemed to help immediately.", "A later score can also reflect new conditions and fatigue.",
     "Film a short set on the next comparable day before reminding yourself of the cue."),
    ("intermediate_progression", "routine", "Intermediate shooting progression", "intermediate shooting progression|next step after stationary shooting|ready for varied practice",
     "Add one new demand at a time when a shot becomes familiar.",
     "Changing location, catch and pace together makes it harder to tell which demand affected performance.",
     "When a player has a comfortable stationary shot and wants better transfer.",
     "Increasing difficulty can temporarily reduce practice accuracy.",
     "Add either a new spot or a moving catch first and keep the other condition familiar."),
])

add("focus", "research_review", [
    ("external_focus", "timing", "Cueing a movement effect", "external focus|outcome cue|focus on ball flight|body part cue",
     "Try one cue about the intended movement effect if body instructions are distracting.",
     "A broad motor-learning review favored external cues across many tasks, though later reanalysis questions how robust the advantage is.",
     "When a player reports thinking about too many joints.", "Cue response varies, and a cue still needs a player-specific check.",
     "Compare one simple target- or flight-related cue with your usual cue in a matched set."),
])

add("focus_bias", "coaching_guidance", [
    ("failed_cue_reassessment", "individual", "Reassessing a cue that did not help", "previous cue did not help|drill didn t help|advice didn t work|cue made it worse",
     "Ask what the player tried before repeating or replacing the cue.",
     "Responses to attentional instructions vary, and a widely taught cue can be a poor fit for this player.",
     "When a player reports that previous advice was ineffective.",
     "The report does not establish a biomechanical explanation for the failure.",
     "Check whether the cue was hard to use or easy to use but unhelpful, then test a clearly different cue only if useful."),
    ("unconventional_maintain", "individual", "Maintaining an effective unusual shot", "should i fix my weird shot|unusual but effective|unconventional mechanics work",
     "Keep a comfortable motion that already serves the player's goal.",
     "An intervention has a cost and evidence on cue superiority is uncertain.",
     "When appearance alone motivates changing an otherwise effective shot.",
     "Reassess if the player reports discomfort or a specific performance problem.",
     "Retest familiar mechanics under the conditions that matter before trying a change."),
])

add("children", "research_review", [
    ("one_cue_youth", "routine", "Simple feedback for young learners", "youth shooting feedback|too many cues for kids|coach a young beginner",
     "Try one short cue a young player can understand and use.",
     "Reviews of children's motor learning consider how instruction timing and format change what a learner takes from feedback.",
     "When a young player is trying to remember several corrections.",
     "The research spans multiple skills, so check whether the cue transfers to basketball shooting.",
     "Let the learner try a small set, then ask which cue they could remember and use."),
    ("feedback_frequency", "routine", "Spacing out feedback", "feedback every shot|too much feedback|when to give shooting feedback",
     "Give a player chances to make their own checks between corrections.",
     "The best feedback frequency and timing can depend on learner and task.",
     "When the player waits for a correction after every attempt.", "Spacing feedback is a practice option, not a fixed prescription.",
     "Try a short set without interruption, then discuss one observation."),
])

add("fatigue", "research_review", [
    ("late_set_fatigue", "routine", "Fatigue and late-set accuracy", "miss late in practice|shooting worse when tired|fatigue and shooting accuracy",
     "Track fatigue separately from technical changes.",
     "A basketball review found that stronger fatigue could reduce accuracy in some shooting tasks.",
     "When a player reports more misses late in a workout.",
     "Clip order or misses alone do not establish fatigue or the affected joint.",
     "Compare a rested set and a normal later set from the same spot, noting perceived effort."),
    ("mental_fatigue", "routine", "Mental fatigue on free throws", "mentally tired free throws|mental fatigue|tired concentration at line",
     "Use a familiar routine when concentration feels lower.",
     "A review reported poorer free-throw accuracy after moderate mental fatigue in the available studies.",
     "When a player reports difficulty focusing after a demanding session.",
     "The research does not diagnose the reason for one person's misses.",
     "Log how mentally fresh you feel beside your normal free-throw outcome counts."),
    ("fatigue_range", "distance", "Fatigue demands can differ by distance", "tired on threes but not twos|fatigue three point shooting|range drops when tired",
     "Separate distances when checking shooting under fatigue.",
     "A review found that fatigue intensity and shot distance influenced the observed effects on accuracy.",
     "When results seem to fade farther from the basket.", "Study fatigue protocols do not reproduce every player's practice.",
     "Log easy-location and longer-location sets separately rather than pooling late attempts."),
])

add("sprints", "observational_study", [
    ("fatigue_without_form_change", "individual", "Fatigue and unchanged visible mechanics", "tired but form looks same|fatigue no angle change|fatigue cannot see it",
     "Stable-looking joint positions can coexist with fatigue.",
     "A small elite youth study found no clear change in its measured three-point kinematics after one sprint protocol.",
     "When a player reports fatigue but their pose results look similar.",
     "This does not show that fatigue never affects shooting.",
     "Keep the player's fatigue report and the measured comparison separate."),
])

add("warmup", "research_review", [
    ("neuromuscular_warmup", "landing", "Neuromuscular warm-up for basketball", "injury prevention|neuromuscular warmup|neuromuscular warm up",
     "A regular warm-up can include balance and controlled movement before harder basketball activity.",
     "Basketball reviews report promising lower-limb injury prevention evidence with variation among studies.",
     "Before normal basketball practice when the player is healthy enough to participate.",
     "Warm-up does not guarantee injury prevention or treat an existing injury.",
     "Use familiar low-intensity movement before progressing to normal jumps and changes of direction."),
    ("landing_warmup", "landing", "Preparing for jumping and landing", "warm up for jumping|prepare for jump shots|landing warm up",
     "Include controlled landing practice in a comfortable warm-up.",
     "Balance and landing exercises occur in basketball neuromuscular programs as part of a wider routine.",
     "When progressing from easy movement to jump shooting.",
     "An individual landing drill has no guaranteed protective effect.",
     "Rehearse gentle stops and comfortable landings before adding normal game-speed movement."),
])

add("youth", "coaching_guidance", [
    ("youth_equipment", "mechanics", "Equipment fit for a young shooter", "ball too heavy for kids|youth hoop height|younger player range|smaller basketball for beginners",
     "Check equipment and shooting distance when a young player struggles to reach the rim.",
     "Youth guidelines use age-appropriate equipment to make the task fit the player.",
     "When the player is learning with an adult-size ball or hoop.",
     "Choose equipment from the applicable age-group guidance rather than a universal size.",
     "If appropriate equipment is available, compare comfortable attempts before changing mechanics."),
    ("youth_rest", "routine", "Rest in a youth practice schedule", "youth rest days|practice every day kids|youth shooting workload|overuse youth basketball",
     "Leave recovery time in the schedule for younger players.",
     "Youth guidelines include age-specific participation limits and recovery recommendations.",
     "When a young player is adding shooting sessions on top of team practice.",
     "These are general guidelines; total sport activity and individual needs vary.",
     "Count the existing team and individual activity when planning another shooting session."),
])

add("pain", "clinical_guidance", [
    ("movement_comfort", "safety", "Shooting comfort and pain", "shoulder pain shooting|shoulder aches when i shoot|shooting through shoulder pain",
     "Treat recurring pain as a separate issue from technique feedback.",
     "Footage and pose estimates cannot diagnose the source of pain.",
     "When the player reports shoulder pain that persists or worsens.",
     "Avoid prescribing a shooting drill to treat pain.",
     "Pause the movement that aggravates it and seek qualified assessment if it persists or worsens."),
])

add("rookie", "coaching_guidance", [
    ("no_basket_delivery", "release", "Delivery practice without a basket", "shooting without a hoop|no basket shooting|practice release without hoop",
     "Use a low-risk rehearsal to practice how the delivery feels when a basket is unavailable.",
     "Removing the hoop can make it easier to narrow attention to the finish.",
     "When there is clear space and the player wants a non-scoring practice option.",
     "Without a hoop, this cannot measure shooting accuracy or flight into the basket.",
     "Rehearse a relaxed lift and finish without releasing the ball if space is limited."),
])
