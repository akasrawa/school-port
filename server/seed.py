"""Demo data: the principal, a teacher, students and the four sample English exams (Grades 3–6)."""
import os
import random
import shutil

from flask import current_app
from werkzeug.security import generate_password_hash

from .grading import load_questions, recalc_attempt
from .utils import jd, now

MEDIA_SRC = os.path.join(os.path.dirname(__file__), "seed_media")


def S(title, body="", image=None):
    return {"type": "section", "text": title, "description": body, "image": image, "points": 0}


def MCQ(text, options, correct, points=1, image=None, help_text=""):
    return {"type": "mcq", "text": text, "options": options, "correct": correct, "points": points, "image": image, "description": help_text}


def SHORT(text, answers, points=1, image=None, help_text=""):
    return {"type": "short", "text": text, "correct": answers, "points": points, "image": image, "description": help_text}


def FILL(text, template, points, bank=False, distractors=None, help_text=""):
    return {"type": "fill", "text": text, "description": help_text, "points": points,
            "options": {"template": template, "bank": bank, "distractors": distractors or []}}


def ORDER(text, answers, points=1):
    return {"type": "order", "text": text, "correct": answers, "points": points}


def MATCH(text, pairs, points, distractors=None):
    return {"type": "match", "text": text, "points": points, "options": {"pairs": pairs, "distractors": distractors or []}}


def TF(text, correct, points=1):
    return {"type": "truefalse", "text": text, "correct": correct, "points": points}


def ESSAY(text, points, image=None, help_text=""):
    return {"type": "paragraph", "text": text, "points": points, "image": image, "description": help_text}


def look(text, options, answer, image):
    return MCQ(text, options, options.index(answer), 1, image)


GRADE4 = {
    "title": "Top Goal 1 – Units 1 & 2 Exam",
    "subject": "English", "grade": "Grade 4", "class": "Grade 4 – A",
    "description": "Read each question carefully. Look at the pictures and choose the correct answer.\nGood luck!",
    "questions": [
        S("Question 1: Look and circle. (4 marks)"),
        look("1. Who is this?", ["son", "daughter", "grandma"], "daughter", "g4_daughter.png"),
        look("2. Who is this?", ["son", "grandpa", "daughter"], "son", "g4_son.png"),
        look("3. Who is this?", ["grandpa", "daughter", "grandma"], "grandma", "g4_grandma.png"),
        look("4. Who is this?", ["grandpa", "son", "grandma"], "grandpa", "g4_grandpa.png"),
        S("Question 2: Look and circle. (5 marks)"),
        look("1. What is this?", ["bus", "bed", "book"], "bus", "g4_bus.png"),
        look("2. What is this?", ["bus", "bed", "book"], "bed", "g4_bed.png"),
        look("3. What is this?", ["broom", "trash can", "bus"], "trash can", "g4_trashcan.png"),
        look("4. What is this?", ["bed", "book", "bus"], "book", "g4_book.png"),
        look("5. What is this?", ["broom", "trash can", "bed"], "broom", "g4_broom.png"),
        S("Question 3: Look and circle. (5 marks)"),
        look("1. How does he feel? / What is he like?", ["strong", "shy", "tired"], "strong", "g4_strong.png"),
        look("2. How does he feel?", ["kind", "tired", "strong"], "tired", "g4_tired.png"),
        look("3. What is he like?", ["shy", "chatty", "kind"], "shy", "g4_shy.png"),
        look("4. What is she like?", ["tired", "shy", "kind"], "kind", "g4_kind.png"),
        look("5. What is he like?", ["chatty", "strong", "tired"], "chatty", "g4_chatty.png"),
        S("Question 4: Circle the correct answer. (6 marks)"),
        MCQ("1. How often ____ you walk in the park?", ["do", "does", "is"], 0),
        MCQ("2. How often ____ she walk in the park?", ["do", "does", "are"], 1),
        MCQ("3. I ____ go to school. I go every day.", ["always", "never", "rarely"], 0),
        MCQ("4. Omar ____ his comic book now.", ["reads", "is reading", "read"], 1),
        MCQ("5. Fatima ____ to school by bus every day.", ["goes", "is going", "go"], 0),
        MCQ("6. ____ you help me, please?", ["Can", "Does", "Is"], 0),
    ],
}

GRADE3 = {
    "title": "Grade 3 – First Exam (Units 1 and 2)",
    "subject": "English", "grade": "Grade 3", "class": "Grade 3 – A", "time": 40,
    "description": "English Language · First Period Exam · Time: 40 min · Total: 20 marks",
    "questions": [
        S("Q1. Match (Level 1 – Easy) · 4 marks"),
        MATCH("Match the question with the answer.", [
            ["Where do you live?", "I live in Jeddah."],
            ["How old are you?", "I'm eleven years old."],
            ["What's your name?", "My name's Hashim."],
            ["What do you think about whales?", "I think whales are big."],
        ], 4),
        S("Q2. Phonics: choose the letters (Level 1 – Easy) · 3 marks", "( oa – ow – ee – ai – i_e – y )"),
        dict(FILL("Write the missing letters.", "g[oa]t", 0.5, help_text="oa – ow – ee – ai – i_e – y"), image="g3_goat.png"),
        dict(FILL("Write the missing letters.", "c[ow]", 0.5, help_text="oa – ow – ee – ai – i_e – y"), image="g3_cow.png"),
        dict(FILL("Write the missing letters.", "sh[ee]p", 0.5, help_text="oa – ow – ee – ai – i_e – y"), image="g3_sheep.png"),
        dict(FILL("Write the missing letters.", "tr[ai]n", 0.5, help_text="oa – ow – ee – ai – i_e – y"), image="g3_train.png"),
        dict(FILL("Write the missing letters.", "k[i]t[e]", 0.5, help_text="oa – ow – ee – ai – i_e – y"), image="g3_kite.png"),
        dict(FILL("Write the missing letters.", "fl[y]", 0.5, help_text="oa – ow – ee – ai – i_e – y"), image="g3_fly.png"),
        S("Q3. Complete the conversation (Level 1 – Easy) · 3 marks"),
        FILL("Complete with a word from the box.",
             "A: Hello! What's your [name]?\nB: My name's Hashim. Nice to meet you.\nA: How [old] are you?\nB: I'm eleven years old.\nA: Where are you [from]?\nB: I'm from Jeddah.", 3, bank=True),
        S("Q4. Choose the correct answer (Level 2 – Medium) · 4 marks"),
        MCQ("1. Sharks are ......... than whales.", ["fast", "faster", "fastest"], 1),
        MCQ("2. A baby seal is the ......... .", ["cute", "cuter", "cutest"], 2),
        MCQ("3. A whale is ......... than a seahorse.", ["big", "bigger", "biggest"], 1),
        MCQ("4. The dolphin is the ......... sea animal.", ["fast", "faster", "fastest"], 2),
        S("Q5. Reorder the words (Level 2 – Medium) · 2 marks"),
        ORDER("1. Put the words in order.", ["I / think / sharks / are / scary"]),
        ORDER("2. Put the words in order.", ["Nice / to / meet / you"]),
        S("Q6. Look and write the sea animal (Level 3 – Challenge) · 4 marks", "seal · dolphin · seahorse · shark"),
        SHORT("1. Write the sea animal.", ["dolphin", "a dolphin"], 1, "g3_dolphin.png"),
        SHORT("2. Write the sea animal.", ["seahorse", "a seahorse", "sea horse"], 1, "g3_seahorse.png"),
        SHORT("3. Write the sea animal.", ["seal", "a seal"], 1, "g3_seal.png"),
        SHORT("4. Write the sea animal.", ["shark", "a shark"], 1, "g3_shark.png"),
    ],
}

GRADE5 = {
    "title": "First Term Exam – Grade 5 (Units 1 & 2)",
    "subject": "English", "grade": "Grade 5", "class": "Grade 5 – A",
    "description": "Answer all questions. Total: 20 marks.",
    "questions": [
        S("Question 1: Complete with a word from the box (3 marks)"),
        FILL("Complete with a word from the box.",
             "1. Turn on the [Wi-Fi|wifi|wi fi] to use the internet.\n2. The [architect] drew the design of the house.\n3. The soup was [horrible]. It tasted awful.",
             3, bank=True, distractors=["basement"]),
        S("Question 2: Write the opposite (2 marks)"),
        SHORT("lucky", ["unlucky"], 1, help_text="Write the opposite."),
        SHORT("kind", ["unkind"], 1, help_text="Write the opposite."),
        S("Question 3: Write A (action) or S (state) (4 marks)"),
        MATCH("Is the verb an action (A) or a state (S)?", [
            ["run", "A (action)"], ["love", "S (state)"], ["believe", "S (state)"], ["write", "A (action)"]], 4),
        S("Question 4: Write the correct form of the verb (3 marks)"),
        FILL("Write the correct form of the verb.",
             "1. Last Monday my team [won] the game. (win)\n2. On Tuesdays we [dance] to music. (dance)\n3. [Did] you [go] to the youth center last week? (go)", 3),
        S("Question 5: Will, Won't, Be going to (3 marks)"),
        FILL("Use will.", "It's dark! I [will turn on|'ll turn on] the light now. (turn on)", 1),
        FILL("Use be going to.", "I bought the tickets last week. We [are going to visit|'re going to visit] the zoo tomorrow. (visit)", 1),
        SHORT("Correct the mistake: “I will to call you tonight.”", ["I will call you tonight", "I'll call you tonight"], 1),
        S("Question 6: Reading (3 marks)",
          "My special interest is origami. It is an amazing art form. I started origami three years ago. Some kids were unkind to me at school and I didn't have many friends. After a horrible day, I found a book about origami on the sidewalk. So in the end, I was very lucky that day! I go to an origami club every Thursday. Last month, I met a lovely group of friends there!\n\nAdapted from the text “My Special Interest” (Rose), Unit 1."),
        SHORT("1. What is Rose's special interest?", ["origami", "her special interest is origami", "it is origami", "it's origami"], 1),
        SHORT("2. When does Rose go to the origami club?", ["every Thursday", "on Thursdays", "on Thursday", "Thursday", "she goes every Thursday"], 1),
        ESSAY("3. Why was Rose lucky that day?", 1),
        S("Question 7: Writing (2 marks)", "Complete the sentences about your dream bedroom."),
        ESSAY("1. In my dream bedroom, I will have …", 1),
        ESSAY("2. I am going to …", 1),
    ],
}

GRADE6 = {
    "title": "First Term English Exam – Grade 6 (Units 1 & 2)",
    "subject": "English", "grade": "Grade 6", "class": "Grade 6 – A",
    "description": "Answer all questions. Total: 20 marks.",
    "questions": [
        S("Question 1: Look and write a sentence with “where”. (2 marks)"),
        ESSAY("1. the jungle", 1, "g6_jungle.png", "Write a sentence with “where”."),
        ESSAY("2. the desert", 1, "g6_desert.png", "Write a sentence with “where”."),
        S("Question 2: Change active to passive or passive to active. (2 marks)"),
        SHORT("1. Dinosaur bones are studied by scientists.", ["Scientists study dinosaur bones"], 1),
        SHORT("2. People don't see wild animals in houses.", [
            "Wild animals aren't seen in houses", "Wild animals are not seen in houses",
            "Wild animals aren't seen in houses by people", "Wild animals are not seen in houses by people"], 1),
        S("Question 3: Complete with is, are or where. (2 marks)"),
        FILL("Complete with is, are or where.",
             "1. The jungle [is] where tigers hunt.\n2. The trees [are] where monkeys play.\n3. The ocean is [where] sharks live.\n4. Forests are [where] birds build their nests.", 2, bank=True),
        S("Question 4: Order the words to make sentences. (3 marks)"),
        ORDER("1. camels / the desert / live / is / where", ["The desert / is / where / camels / live"]),
        ORDER("2. is / the ocean / where / sharks / found / are", ["The ocean / is / where / sharks / are / found"]),
        ORDER("3. trees / the forest / full of / is / where / tigers / hunt", ["The forest / is / full of / trees / where / tigers / hunt"]),
        S("Question 5: Complete with the correct verb form. (2 marks)"),
        FILL("Complete with the correct verb form.",
             "1. If patients rest well, they [get|will get] better. (get)\n2. If you don't rest, you [don't get|won't get|will not get|do not get] well. (not get)\n3. If you fall on your elbow, you [break|will break|might break] it. (break)\n4. If you go to the hospital, they [give|will give] you an X-ray. (give)", 2),
        S("Question 6: Order the words to make questions. (2 marks)"),
        ORDER("1. is / the desert / where / camels / live ?", ["Is / the desert / where / camels / live ?"]),
        ORDER("2. is / the ocean / where / dolphins / are / found ?", ["Is / the ocean / where / dolphins / are / found ?"]),
        S("Question 7: Correct the mistake. Write the sentence again. (2 marks)"),
        SHORT("1. Is the trees where monkeys play?", ["Are the trees where monkeys play"], 1),
        SHORT("2. The forest is when birds lay their eggs.", ["The forest is where birds lay their eggs"], 1),
        S("Question 8: Read the text and answer. (3 marks)",
          "In our travels around the world, my cousin Aisha and I tasted lots of different kinds of food and took some cooking classes, too. Some dishes were really tasty, but we didn't like others.\n\nLast year, we ate at a local market. We tried a few fried dough snacks. They were sweet, and we ate them with a warm chocolate sauce. It was a really nice snack!\n\nIn another country, we went to a famous restaurant and had soup with a little meat and a few olives. Aisha didn't like it much; it was mainly water. I don't think the meat was cooked well, and I think there were mice in the kitchen. Yuck!"),
        TF("A1. Aisha and the writer are cousins.", "true", 0.5),
        TF("A2. They ate the fried dough snacks with warm chocolate sauce.", "true", 0.5),
        TF("A3. Aisha loved the soup.", "false", 0.5),
        TF("A4. They had the soup at a local market.", "false", 0.5),
        ESSAY("B. Why didn't Aisha like the soup?", 1),
        S("Question 9: Writing (2 marks)"),
        ESSAY("Write two sentences with “where” about two different places.", 2),
    ],
}


def FILE(text, points, help_text=""):
    return {"type": "file", "text": text, "points": points, "description": help_text}


LUGHATI6 = {
    "title": "لغتي – اختبار الفترة الأولى – الصف السادس",
    "subject": "لغتي", "grade": "الصف السادس", "class": "Grade 6 – A", "time": 40,
    "description": "اختبار الفترة الأولى – الفصل الدراسي الأول ١٤٤٨هـ · الزمن: ٤٠ دقيقة · الدرجة الكلية: ٢٠",
    "questions": [
        S("السؤال الأول: فهم المقروء (٦ درجات)",
          "خير وسيلة للنجاح في الحياة أن يكون للإنسان مثلٌ أعلى عظيم، يضعه دائمًا نُصب عينيه، ويسعى دائبًا في الوصول إليه، وخير قدوة أمرنا بالاقتداء به نبينا محمد ﷺ، قال تعالى: ﴿لقد كان لكم في رسول الله أسوة حسنة﴾، وصحابته الكرام، وقد يكون عالمًا عظيمًا، أو أديبًا بارعًا، أو سياسيًّا خبيرًا.\n\n"
          "كان عبد الله بن عمر من أكثر الناس اقتداءً بسيرة النبي محمد ﷺ، ومن أكثرهم تتبعًا لآثاره، فقد روى عن رسول الله ﷺ (٢٦٣٠) حديثًا.\n\n"
          "وُلد ابن عمر بمكة في السنة الثالثة من بعثة النبي ﷺ، فقد أسلم صغيرًا، وهاجر إلى المدينة مع أبيه وهو ابن إحدى عشرة سنة.\n\n"
          "عُرض على رسول الله ﷺ يوم بدر ويوم أحد ليحارب معه المشركين فاستصغره، وأجازه يوم الخندق وهو يومئذٍ ابن خمس عشرة سنة، فشهد الخندق وما بعده مع رسول الله ﷺ، وشهد بعده اليرموك وفتح مصر وشمال أفريقيا.\n\n"
          "وعُرف ابن عمر بالزهد والتقوى والعبادة، وشهد رسول الله ﷺ له: «نِعمَ الرجلُ عبدُ الله»."),
        MCQ("١- ما أهمية القدوة الحسنة في حياتنا؟", ["خير وسيلة للنجاح", "نفتخر بها على غيرنا", "تؤدي أعمالنا"], 0),
        MCQ("٢- من المثل الأعلى الذي أمرنا بالاقتداء به؟", ["الرسول محمد ﷺ", "الأبوين", "الصحابة"], 0),
        MCQ("٣- الغزوة التي شهدها عبد الله بن عمر مع النبي ﷺ:", ["غزوة أحد", "غزوة الخندق", "فتح مصر"], 1),
        MCQ("٤- متى وُلد عبد الله بن عمر؟", ["في السنة الثالثة من الهجرة", "في السنة الثالثة من البعثة", "في السنة الحادية عشرة للبعثة"], 1),
        ESSAY("٥- ما السبب في كثرة روايات عبد الله بن عمر عن رسول الله ﷺ؟", 1),
        ESSAY("٦- لماذا لم يشهد عبد الله بن عمر غزوة بدر؟", 1),
        S("السؤال الثاني: اختر الإجابة الصحيحة (٤ درجات)"),
        MCQ("١- نِعمَ صديقُ الإنسانِ الوفيُّ.", ["نِعمَ", "صديقُ الإنسانِ", "الوفيُّ"], 2, help_text="(المخصوص بالمدح في الأسلوب السابق)"),
        MCQ("٢- الجملة التي كُتبت بشكل صحيح:", ["عمر إبن الخطاب", "عمر بن الخطاب", "عمر ابن الخطاب"], 1),
        MCQ("٣- .......... الجوُّ حارًّا.", ["كان", "صار", "ليس"], 2, help_text="(أكمل بفعل يفيد النفي)"),
        MCQ("٤- يا .......... ما أنت ببخيل.", ["ابنَ الأكارم", "بنَ الأكارم", "إبنَ الأكارم"], 0, help_text="(أكمل)"),
        S("السؤال الثالث: ضع علامة (✓) أمام العبارة الصحيحة وعلامة (✗) أمام الخاطئة (٣ درجات)"),
        TF("١- «بئس» فعل ماضٍ جامد للذم.", "true"),
        TF("٢- ترتيب الحركات من الأقوى إلى الأضعف: الفتحة فالضمة ثم الكسرة فالسكون.", "false"),
        TF("٣- كل الحروف همزتها همزة قطع ما عدا «ال» التعريف.", "true"),
        S("السؤال الرابع: الظاهرة الإملائية (٤ درجات)", "أ- اختر الإجابة الصحيحة:"),
        MCQ("١- أسلم عمرُ بنُ الخطاب في السنة السادسة من البعثة. حُذفت همزة (ابن) لأنها:",
            ["وقعت بين علمين الثاني أب للأول", "وقعت في أول السطر", "وقعت بعد النداء"], 0, points=0.75),
        MCQ("٢- آمنت .......... فرعون بالله.", ["امرأةُ", "إمرأةُ", "أمرأةُ"], 0, points=0.75),
        MCQ("٣- .......... في ميزان حسناتكم.", ["عطاؤكم", "عطائكم", "عطاءكم"], 0, points=0.75),
        SHORT("٤- __يَنَشَئ__ الفتى على مكارم الأخلاق.", ["ينشأ", "يَنشأ", "يَنْشَأُ", "ينشأُ"], 0.75, help_text="صوّب ما تحته خط."),
        ESSAY("ب- اكتب ما يُملى عليك.", 1, help_text="استمع للتسجيل الصوتي ثم اكتب."),
        S("السؤال الخامس: الرسم الكتابي (٣ درجات)"),
        {"type": "draw", "text": "اكتب ما يلي بخط النسخ:", "description": "كان عبد الله بن عمر من أكثر الصحابة اقتداءً بسيرة النبي محمد ﷺ.",
         "points": 3, "options": {"lines": True, "height": 380}},
    ],
}

ISLAMIC6 = {
    "title": "الدراسات الإسلامية – اختبار منتصف الفصل – الصف السادس",
    "subject": "الدراسات الإسلامية", "grade": "الصف السادس", "class": "Grade 6 – A", "time": 30,
    "description": "اختبار منتصف الفصل الدراسي الأول ١٤٤٨هـ · الدرجة الكلية: ١٥\nمع تمنياتي لكم بالتوفيق والنجاح.",
    "questions": [
        S("السؤال الأول: اختر الإجابة الصحيحة فيما يلي (٩ درجات)"),
        MCQ("١. من أركان الإيمان:", ["الإيمان بالملائكة", "صوم رمضان", "إيتاء الزكاة"], 0),
        MCQ("٢. الشرك الأكبر من أعظم:", ["منقصات الإيمان", "المكروهات التي تحبط العمل", "نواقض الإيمان"], 2),
        MCQ("٣. من أنكر ركنًا من أركان الإيمان فإنه:", ["خارج من ملة الإسلام", "لا يخرج من ملة الإسلام", "ارتكب ذنبًا"], 0),
        MCQ("٤. اعتقاد بالقلب وقول باللسان وعمل بالجوارح، يزيد بالطاعة وينقص بالمعصية، هو:", ["الإيمان", "الإحسان", "التوحيد"], 0),
        MCQ("٥. كان عابدًا شجاعًا، نزل عليه النبي ﷺ لما قدم المدينة وأقام عنده حتى بنى بيته ومسجده، هو الصحابي:",
            ["خالد بن زيد الأنصاري (أبو أيوب)", "أنس بن مالك", "عبد الله بن مسعود"], 0),
        MCQ("٦. المراد بذوي الرحم هم الأقارب من جهة:", ["الأم فقط", "الأم والأب", "الأب فقط"], 1),
        MCQ("٧. من مستحبات يوم الجمعة:", ["قراءة سورة الكهف", "قراءة سورة الغاشية", "قراءة سورة الجمعة"], 0),
        MCQ("٨. صرف نوع من أنواع العبادة لغير الله تعريف:", ["الشرك", "الشرك الأكبر", "الشرك الأصغر"], 0),
        MCQ("٩. من حكمة مشروعية العيد شكر الله تعالى على إتمام عبادتي:", ["الصلاة والصيام", "الصلاة والحج", "الصوم والحج"], 2),
        S("السؤال الثاني: صِل بين عبارات العمود (أ) بما يناسبها في العمود (ب) (٦ درجات)"),
        MATCH("اختر لكل عبارة الآية المناسبة:", [
            ["ولاية الله للمؤمنين", "﴿اللَّهُ وَلِيُّ الَّذِينَ آمَنُوا﴾"],
            ["أن الله لا يغفر للمشرك", "﴿إِنَّ اللَّهَ لَا يَغْفِرُ أَن يُشْرَكَ بِهِ وَيَغْفِرُ مَا دُونَ ذَٰلِكَ لِمَن يَشَاءُ﴾"],
            ["حكم صلاة الجمعة", "﴿يَا أَيُّهَا الَّذِينَ آمَنُوا إِذَا نُودِيَ لِلصَّلَاةِ مِن يَوْمِ الْجُمُعَةِ فَاسْعَوْا إِلَىٰ ذِكْرِ اللَّهِ﴾"],
            ["التكبير في العيد", "﴿وَلِتُكْمِلُوا الْعِدَّةَ وَلِتُكَبِّرُوا اللَّهَ عَلَىٰ مَا هَدَاكُمْ﴾"],
            ["بعض معبودات المشركين", "﴿وَيَعْبُدُونَ مِن دُونِ اللَّهِ مَا لَا يَضُرُّهُمْ وَلَا يَنفَعُهُمْ﴾"],
            ["الشرك يحبط جميع الأعمال", "﴿وَلَوْ أَشْرَكُوا لَحَبِطَ عَنْهُم مَّا كَانُوا يَعْمَلُونَ﴾"],
        ], 6),
    ],
}

SAMPLES = [
    (GRADE3, "grade3e1"), (GRADE4, "grade4e1"), (GRADE5, "grade5e1"), (GRADE6, "grade6e1"),
    (LUGHATI6, "lughati6"), (ISLAMIC6, "islamic6"),
]


STUDENTS = {
    "Grade 4 – A": ["Sara Ahmad", "Lama Omar", "Huda Ali", "Reem Khaled", "Noor Saeed", "Joud Hassan", "Layan Youssef", "Dana Fahad"],
    "Grade 3 – A": ["Maryam Nasser", "Aya Sami", "Tala Majed", "Ruba Adel"],
    "Grade 5 – A": ["Hala Jamal", "Lina Tariq", "Farah Rami"],
    "Grade 6 – A": ["Rawan Ziad", "Yara Kareem", "Salma Bassam"],
}


def _copy_media():
    """Store the sample exams' pictures (disk or database, whichever this install uses)."""
    from . import storage

    if not os.path.isdir(MEDIA_SRC):
        return
    for name in sorted(os.listdir(MEDIA_SRC)):
        if not storage.exists("media", name):
            with open(os.path.join(MEDIA_SRC, name), "rb") as fh:
                storage.save("media", name, fh.read())


def _add_exam(db, teacher, exam, class_id, stamp, code):
    fid = db.execute(
        """INSERT INTO forms(teacher_id, code, title, description, subject, grade, status, time_limit_min,
           max_attempts, show_results, show_answers, pass_percent, created_at, updated_at)
           VALUES(?,?,?,?,?,?, 'published', ?, 1, 'after_grading', 1, 50, ?, ?)""",
        (teacher, code, exam["title"], exam["description"], exam["subject"], exam["grade"], exam.get("time", 45), stamp, stamp),
    ).lastrowid
    db.execute("INSERT INTO form_classes(form_id, class_id) VALUES(?,?)", (fid, class_id))
    for position, q in enumerate(exam["questions"]):
        _insert_seed_question(db, fid, position, q)
    return fid


def _insert_seed_question(db, fid, position, q):
    db.execute(
        """INSERT INTO questions(form_id, position, type, text, description, image, points, required,
           options_json, correct_json, explanation, partial) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            fid, position, q["type"], q["text"], q.get("description", ""), q.get("image"), q.get("points", 1),
            0 if q["type"] == "section" else 1,
            jd(q["options"]) if q.get("options") is not None else None,
            jd(q["correct"]) if q.get("correct") is not None else None,
            "", 1 if q["type"] in ("match", "fill") else 0,
        ),
    )


def _fake_answer(q, right, rng):
    kind = q["type"]
    if kind == "mcq":
        return q["correct"] if right else (q["correct"] + 1) % len(q["options"])
    if kind == "truefalse":
        return q["correct"] if right else ("false" if q["correct"] == "true" else "true")
    return None


def seed_demo(db):
    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]:
        return
    _copy_media()
    stamp = now()
    rng = random.Random(11)

    def add_user(name, username, password, role, email=None):
        return db.execute(
            "INSERT INTO users(name, username, email, password_hash, role, created_at) VALUES(?,?,?,?,?,?)",
            (name, username, email, generate_password_hash(password), role, stamp),
        ).lastrowid

    add_user("المديرة / Principal", "admin", "admin123", "admin", "admin@school.test")
    teacher = add_user("أ. حنين / Ms. Haneen", "teacher", "teacher123", "teacher")
    add_user("أ. سارة / Ms. Sara", "sara", "teacher123", "teacher")

    classes = {}
    for index, name in enumerate(STUDENTS):
        classes[name] = db.execute(
            "INSERT INTO classes(teacher_id, name, join_code, created_at) VALUES(?,?,?,?)",
            (teacher, name, f"demo{index + 3}a", stamp),
        ).lastrowid

    number = 1000
    members = {}
    for class_name, names in STUDENTS.items():
        for name in names:
            number += 1
            sid = add_user(name, str(number), "1234", "student")
            db.execute("UPDATE users SET created_by=? WHERE id=?", (teacher, sid))
            db.execute("INSERT INTO class_members(class_id, student_id) VALUES(?,?)", (classes[class_name], sid))
            members.setdefault(class_name, []).append((sid, name))

    exams = {}
    for exam, code in SAMPLES:
        fid = _add_exam(db, teacher, exam, classes[exam["class"]], stamp, code)
        exams.setdefault(exam["class"], fid)
    fill_bank(db)

    # Student 1001 (Sara, Grade 4) is also assigned the Grade 3 exam individually – shows per-student assignment.
    first_student = members["Grade 4 – A"][0][0]
    db.execute("INSERT INTO form_students(form_id, student_id) VALUES(?,?)", (exams["Grade 3 – A"], first_student))

    # Sample results for Grade 4: five students finished, the demo student (1001) and two others have not started.
    fid = exams["Grade 4 – A"]
    questions = load_questions(db, fid)
    for sid, name in members["Grade 4 – A"][3:]:
        quality = rng.uniform(0.45, 0.98)
        started = stamp - rng.randint(3600, 86400 * 2)
        attempt = db.execute(
            """INSERT INTO attempts(form_id, user_id, taker_name, attempt_no, started_at, submitted_at, status, seed)
               VALUES(?,?,?,1,?,?, 'submitted', ?)""",
            (fid, sid, name, started, started + rng.randint(600, 1500), rng.randint(1, 9999)),
        ).lastrowid
        for q in questions:
            value = _fake_answer(q, rng.random() < quality, rng)
            if value is not None:
                db.execute(
                    "INSERT INTO answers(attempt_id, question_id, value_json) VALUES(?,?,?)",
                    (attempt, q["id"], jd(value)),
                )
        recalc_attempt(db, attempt)
    db.commit()


def fill_bank(db):
    """Put every sample question into the shared question bank (skips ones already there)."""
    from .teacher import bank_add

    for row in db.execute("SELECT id, subject, grade FROM forms WHERE code IN (%s)" % ",".join("?" * len(SAMPLES)),
                          [code for _e, code in SAMPLES]).fetchall():
        for q in load_questions(db, row["id"]):
            if q["type"] != "section":
                bank_add(db, q, row["subject"], row["grade"], "sample")


def install_samples(db, teacher_id):
    """Add the ready-made sample exams (as drafts) to an existing school. Returns how many were added."""
    _copy_media()
    stamp = now()
    added = 0
    for exam, code in SAMPLES:
        if db.execute("SELECT 1 FROM forms WHERE code=?", (code,)).fetchone():
            continue
        fid = db.execute(
            """INSERT INTO forms(teacher_id, code, title, description, subject, grade, status, time_limit_min,
               max_attempts, show_results, show_answers, pass_percent, created_at, updated_at)
               VALUES(?,?,?,?,?,?, 'draft', ?, 1, 'after_grading', 1, 50, ?, ?)""",
            (teacher_id, code, exam["title"], exam["description"], exam["subject"], exam["grade"], exam.get("time", 45), stamp, stamp),
        ).lastrowid
        for position, q in enumerate(exam["questions"]):
            _insert_seed_question(db, fid, position, q)
        added += 1
    fill_bank(db)
    return added
