import json
import os

# Данные каталога (Python словарь: True/False с большой буквы)
data = [
  {
    "slug": "hair",
    "type": "editor",
    "gender": "m",
    "title_ru": "Прическа",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/editor/m/hair/p1.jpg",
        "items": [
          {"slot": 1, "title": "Шторки", "prompt": "curtains hairstyle, middle part hair", "is_premium": False},
          {"slot": 2, "title": "Лысый", "prompt": "bald head, shaved head, skinhead", "is_premium": False},
          {"slot": 3, "title": "Кроп", "prompt": "textured crop haircut, fade", "is_premium": False},
          {"slot": 4, "title": "Дреды", "prompt": "dreadlocks hairstyle", "is_premium": True},
          {"slot": 5, "title": "Маллет 80-х", "prompt": "80s mullet hairstyle, retro hair", "is_premium": True},
          {"slot": 6, "title": "Маллет 2000-х", "prompt": "modern mullet hairstyle", "is_premium": True},
          {"slot": 7, "title": "Длинные волосы", "prompt": "long hair, flowing hair, shoulder length", "is_premium": True},
          {"slot": 8, "title": "Ирокез", "prompt": "mohawk hairstyle, punk hair", "is_premium": True},
          {"slot": 9, "title": "Под машинку", "prompt": "buzz cut, military haircut, short hair", "is_premium": True}
        ]
      },
      {
        "page_number": 2,
        "image_path": "assets/editor/m/hair/p2.jpg",
        "items": [
          {"slot": 1, "title": "Гаврош", "prompt": "gavroche hairstyle, messy texture", "is_premium": True},
          {"slot": 2, "title": "Помпадур", "prompt": "pompadour hairstyle, rockabilly hair", "is_premium": True},
          {"slot": 3, "title": "Андеркат", "prompt": "undercut hairstyle, slicked back top", "is_premium": True},
          {"slot": 4, "title": "Шегги", "prompt": "shaggy hairstyle, messy hair", "is_premium": True},
          {"slot": 5, "title": "Слик Бэк", "prompt": "slicked back hair, mafia style hair", "is_premium": True},
          {"slot": 6, "title": "Кудри", "prompt": "curly hair, perm hairstyle", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "color",
    "type": "editor",
    "gender": "m",
    "title_ru": "Цвет волос",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/editor/m/color/p1.jpg",
        "items": [
          {"slot": 1, "title": "Светлый", "prompt": "blonde hair color", "is_premium": False},
          {"slot": 2, "title": "Неоново-синий", "prompt": "neon blue hair dye", "is_premium": False},
          {"slot": 3, "title": "Рыжий", "prompt": "ginger hair, red hair", "is_premium": True},
          {"slot": 4, "title": "Черный", "prompt": "black hair color", "is_premium": True},
          {"slot": 5, "title": "Кислотно-зеленый", "prompt": "acid green hair dye", "is_premium": True},
          {"slot": 6, "title": "Ярко-розовый", "prompt": "hot pink hair dye", "is_premium": True},
          {"slot": 7, "title": "Каштановый", "prompt": "chestnut brown hair", "is_premium": True},
          {"slot": 8, "title": "Красный", "prompt": "deep red hair dye", "is_premium": True},
          {"slot": 9, "title": "Серебристый", "prompt": "silver grey hair, platinum blonde", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "beard",
    "type": "editor",
    "gender": "m",
    "title_ru": "Борода",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/editor/m/beard/p1.jpg",
        "items": [
          {"slot": 1, "title": "Средняя борода", "prompt": "medium full beard", "is_premium": False},
          {"slot": 2, "title": "Средняя щетина", "prompt": "medium stubble beard", "is_premium": True},
          {"slot": 3, "title": "Короткая борода", "prompt": "short boxed beard", "is_premium": True},
          {"slot": 4, "title": "Небритость", "prompt": "light stubble, 3 day beard", "is_premium": True},
          {"slot": 5, "title": "Длинная борода", "prompt": "long full beard, lumberjack beard", "is_premium": True},
          {"slot": 6, "title": "Эспаньолка", "prompt": "goatee beard", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "moustache",
    "type": "editor",
    "gender": "m",
    "title_ru": "Усы",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/editor/m/moustache/p1.jpg",
        "items": [
          {"slot": 1, "title": "Щеточка", "prompt": "toothbrush mustache", "is_premium": False},
          {"slot": 2, "title": "Подкова", "prompt": "horseshoe mustache", "is_premium": True},
          {"slot": 3, "title": "Закрученные", "prompt": "handlebar mustache", "is_premium": True},
          {"slot": 4, "title": "Морж", "prompt": "walrus mustache, thick mustache", "is_premium": True},
          {"slot": 5, "title": "Натуральные", "prompt": "natural chevron mustache", "is_premium": True},
          {"slot": 6, "title": "Зорро", "prompt": "pencil mustache, thin mustache", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "glasses",
    "type": "editor",
    "gender": "m",
    "title_ru": "Очки",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/editor/m/glasses/p1.jpg",
        "items": [
          {"slot": 1, "title": "Черная оправа", "prompt": "black rimmed eyeglasses", "is_premium": False},
          {"slot": 2, "title": "Спортивные", "prompt": "sport sunglasses, fast glasses", "is_premium": True},
          {"slot": 3, "title": "Хипстерские", "prompt": "transparent frame glasses, hipster glasses", "is_premium": True},
          {"slot": 4, "title": "Круглые винтажные", "prompt": "round tortoise shell glasses, vintage style", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "piercing",
    "type": "editor",
    "gender": "m",
    "title_ru": "Пирсинг",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/editor/m/piercing/p1.jpg",
        "items": [
          {"slot": 1, "title": "Туннели", "prompt": "ear gauges, ear tunnels piercing", "is_premium": False},
          {"slot": 2, "title": "Бровь", "prompt": "eyebrow piercing ring", "is_premium": False},
          {"slot": 3, "title": "Кольцо (правое)", "prompt": "right ear ring piercing", "is_premium": True},
          {"slot": 4, "title": "Кольца (оба уха)", "prompt": "earrings in both ears", "is_premium": True},
          {"slot": 5, "title": "Кольцо (левое)", "prompt": "left ear ring piercing", "is_premium": True},
          {"slot": 6, "title": "Нос (сбоку)", "prompt": "nose stud piercing", "is_premium": True},
          {"slot": 7, "title": "Нос (септум)", "prompt": "septum nose ring", "is_premium": True},
          {"slot": 8, "title": "Губа (сбоку)", "prompt": "lip ring piercing side", "is_premium": True},
          {"slot": 9, "title": "Снейк байтс", "prompt": "snake bites lip piercing", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "sets",
    "type": "shoot",
    "gender": "m",
    "title_ru": "Фотосеты",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/shoots/sets/p1.jpg",
        "items": [
          {"slot": 1, "title": "ЧБ в метро", "prompt": "black and white photography, man standing in subway train, depth of field, cinematic lighting", "is_premium": False},
          {"slot": 2, "title": "Майами", "prompt": "man wearing hawaiian shirt and shorts, standing on miami beach, palm trees, sunny day", "is_premium": False},
          {"slot": 3, "title": "Дождь", "prompt": "portrait of a man in heavy rain, wet face, dramatic night lighting, cinematic", "is_premium": False},
          {"slot": 4, "title": "Пол-лица в воде", "prompt": "artistic photo, man face half submerged in calm water, reflection, b&w", "is_premium": True},
          {"slot": 5, "title": "В толпе", "prompt": "man standing in a busy crowd in subway station, long exposure motion blur people around, focus on subject", "is_premium": True},
          {"slot": 6, "title": "Рамен", "prompt": "man eating ramen noodles in japanese restaurant, chopsticks, steam, neon lights", "is_premium": True},
          {"slot": 7, "title": "Прожектор", "prompt": "studio portrait, man illuminated by a round spotlight beam, dramatic shadows", "is_premium": True},
          {"slot": 8, "title": "Вагон метро", "prompt": "man standing inside subway car, perspective view, urban style", "is_premium": True},
          {"slot": 9, "title": "Буря", "prompt": "man standing on a cliff edge, stormy sea, dark clouds, epic atmosphere", "is_premium": True}
        ]
      },
      {
        "page_number": 2,
        "image_path": "assets/shoots/sets/p2.jpg",
        "items": [
          {"slot": 1, "title": "В зеркале", "prompt": "man in suit looking into a vintage mirror, reflection, noir atmosphere", "is_premium": True},
          {"slot": 2, "title": "Кинопортрет", "prompt": "cinematic portrait of a man, dramatic red background, studio lighting", "is_premium": True},
          {"slot": 3, "title": "Нуар-портрет", "prompt": "film noir style portrait, shadow of blinds on face, black and white", "is_premium": True},
          {"slot": 4, "title": "Ночной город", "prompt": "man sitting in a car at night, rain on window, bokeh city lights, synthwave vibe", "is_premium": True},
          {"slot": 5, "title": "Смарт-кэжуал", "prompt": "man leaning on orange wall, wearing beige coat and sweater, fashion photography", "is_premium": True},
          {"slot": 6, "title": "Минимализм", "prompt": "man sitting on a chair, all white background, minimalist fashion photography, b&w", "is_premium": True},
          {"slot": 7, "title": "Элегантный монохром", "prompt": "elegant b&w portrait, man smiling with hands clasped, studio grey background", "is_premium": True},
          {"slot": 8, "title": "Закат", "prompt": "man standing against a wall with sunset shadows, golden hour lighting", "is_premium": True},
          {"slot": 9, "title": "Урбан", "prompt": "man standing in the middle of a busy street, motion blur crowd, high angle shot", "is_premium": True}
        ]
      },
      {
        "page_number": 3,
        "image_path": "assets/shoots/sets/p3.jpg",
        "items": [
          {"slot": 1, "title": "Мотопауза", "prompt": "man sitting on a motorcycle, urban background, black and white photography", "is_premium": True},
          {"slot": 2, "title": "Тень и крыло", "prompt": "dark portrait of a man with a black crow on shoulder, gothic atmosphere", "is_premium": True},
          {"slot": 3, "title": "Теплый сад", "prompt": "man leaning on a stone wall in a garden, greenery, soft sunlight", "is_premium": True},
          {"slot": 4, "title": "Тихий уют", "prompt": "man sitting in a wicker chair, beige interior, relaxed atmosphere", "is_premium": True},
          {"slot": 5, "title": "Ретро портрет", "prompt": "retro 70s style portrait, man wearing patterned vest and gold chain, brown background", "is_premium": True},
          {"slot": 6, "title": "Ночная стоянка", "prompt": "man leaning on a black car at night, street lights, trees background", "is_premium": True},
          {"slot": 7, "title": "Ночной звонок", "prompt": "man talking on a payphone on a night street, cinematic lighting", "is_premium": True},
          {"slot": 8, "title": "Солидный смокинг", "prompt": "man adjusting cufflinks in a tuxedo, dark moody background, luxury style", "is_premium": True},
          {"slot": 9, "title": "Ретро-апатия", "prompt": "man sitting in a messy room with posters, vintage 90s grunge aesthetic", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "looks",
    "type": "shoot",
    "gender": "m",
    "title_ru": "Готовые образы",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/shoots/looks/p1.jpg",
        "items": [
          {"slot": 1, "title": "Гот", "prompt": "goth style man, pale skin, black makeup, gothic clothes", "is_premium": False},
          {"slot": 2, "title": "Адидас-гопник", "prompt": "slavic gopnik style, wearing adidas tracksuit and beanie, squatting", "is_premium": False},
          {"slot": 3, "title": "Эльф", "prompt": "fantasy elf man, long white hair, elven ears, fantasy clothes", "is_premium": False},
          {"slot": 4, "title": "Ретро-хиппи", "prompt": "70s hippie man, long hair, headband, colorful vest, peace sign", "is_premium": True},
          {"slot": 5, "title": "Серфер", "prompt": "surfer guy, messy wet blonde hair, tanned skin, necklace, smiling", "is_premium": True},
          {"slot": 6, "title": "Бродяга", "prompt": "homeless man style, dirty clothes, beanie, street background", "is_premium": True},
          {"slot": 7, "title": "Корпоративный", "prompt": "corporate office worker, suit and tie, glasses, professional photo", "is_premium": True},
          {"slot": 8, "title": "Я в старости", "prompt": "old man, wrinkles, gray hair, realistic aging, same face features", "is_premium": True},
          {"slot": 9, "title": "Фото на паспорт", "prompt": "biometric passport photo, neutral expression, white background, bad lighting style", "is_premium": True}
        ]
      },
      {
        "page_number": 2,
        "image_path": "assets/shoots/looks/p2.jpg",
        "items": [
          {"slot": 1, "title": "Рок-звезда", "prompt": "rock star, long messy hair, leather jacket, tattoos, attitude", "is_premium": True},
          {"slot": 2, "title": "Рэп-исполнитель", "prompt": "rap artist, cap, chains, oversized hoodie, studio background", "is_premium": True},
          {"slot": 3, "title": "Берлинский", "prompt": "berlin techno raver, bleached hair, black outfit, glasses, industrial background", "is_premium": True},
          {"slot": 4, "title": "Комсомол", "prompt": "soviet komsomol member, vintage suit, red tie, lenin pin, 1960s style", "is_premium": True},
          {"slot": 5, "title": "Панк", "prompt": "punk rocker, colorful mohawk, studded leather jacket, eyeliner", "is_premium": True},
          {"slot": 6, "title": "Эмо", "prompt": "2007 emo boy, black fringe hair covering eye, eyeliner, black hoodie", "is_premium": True},
          {"slot": 7, "title": "Восточный стиль", "prompt": "sultan, wearing green and gold traditional eastern robe, turban, rich background", "is_premium": True},
          {"slot": 8, "title": "Я в детстве", "prompt": "young boy, 8 years old, childhood portrait, same face features", "is_premium": True},
          {"slot": 9, "title": "Викинг", "prompt": "viking warrior, fur armor, braids, rugged look", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "winter",
    "type": "shoot",
    "gender": "m",
    "title_ru": "Зимние стили",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/shoots/winter/p1.jpg",
        "items": [
          {"slot": 1, "title": "Зимний характер", "prompt": "man sitting on the hood of black bmw in winter forest, snow, leather jacket", "is_premium": False},
          {"slot": 2, "title": "Русская зима", "prompt": "man in sheepskin coat and fur hat, holding tea glass, samovar on table, russian winter village", "is_premium": True},
          {"slot": 3, "title": "Домашнее Рождество", "prompt": "man sitting in armchair near christmas tree, wearing cozy beige sweater, warm lighting", "is_premium": True},
          {"slot": 4, "title": "Зимний букет", "prompt": "man holding large winter bouquet with cotton and fir branches, snowy street background", "is_premium": True},
          {"slot": 5, "title": "Лесная свежесть", "prompt": "portrait of a man in winter forest, wearing scarf and coat, snowflakes", "is_premium": True},
          {"slot": 6, "title": "Холодные мысли", "prompt": "cinematic split screen, man looking at snowy mountains landscape, cold tones", "is_premium": True}
        ]
      }
    ]
  },
  {
    "slug": "trends",
    "type": "shoot",
    "gender": "m",
    "title_ru": "Тренды",
    "pages": [
      {
        "page_number": 1,
        "image_path": "assets/shoots/trends/p1.jpg",
        "items": [
          {"slot": 1, "title": "Зимняя тишина", "prompt": "collage of 3 photos, man in winter forest, blue tones, scarf", "is_premium": False},
          {"slot": 2, "title": "Снегопад", "prompt": "collage of 3 photos, man holding transparent umbrella in heavy snow", "is_premium": True},
          {"slot": 3, "title": "В галерее", "prompt": "man face as a painting in art gallery, museum lighting", "is_premium": True},
          {"slot": 4, "title": "В галерее (со зрителем)", "prompt": "man face as a large painting in art gallery, viewed by a person from back", "is_premium": True}
        ]
      }
    ]
  }
]
print('d')
def generate_json_file():
    with open("catalog_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✅ Файл catalog_data.json успешно создан!")

if __name__ == "__main__":
    generate_json_file()