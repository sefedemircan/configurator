# Frontend Try-On Bağlantı Rehberi (Nokta Atışı)

Bu doküman, `otomai-web` (veya başka frontend) tarafının **referans ürün görselini kendi başına çıkarmaya çalışmadan** doğrudan bu FastAPI try-on servisine nasıl bağlanacağını tarif eder.

## 1) Ana kural

Try-on için kritik olan şey ürün adı değildir.

Kritik olan tek görsel alan:

```txt
product_layers.base = seçilen variant'ın Shopify CDN image URL'i
```

Frontend ürün kartından / chat önerisinden sadece title alıp “referans çıkarayım” dememelidir.
Referans görsel URL hazır gelmeli ve bu API’ye aynen iletilmelidir.

## 2) Neden frontend’de bozuluyor?

Yaygın hata:

- Ürün seviyesinde kalmak (`Advanced Design`)
- Variant’ı kaçırmak (`Siyah`, `Bej`, `Siyah-Kırmızı` ...)
- `featuredImage` / ilk galeri görselini kullanmak
- Chat metninden ürün görseli “tahmin etmek”

Doğru davranış:

- Kullanıcı ürün + renkte netleşince
- O satıra ait `image_url` alınır
- Bu URL `product_layers.base` ve `product_reference.image_url` olarak API’ye gider

Örnek:

- Yanlış: `Otom Advanced Design Universal Babyface...` (tek ürün, 1 görsel)
- Doğru: `Otom Advanced Design Universal Babyface... — Siyah` (variant satırı + kendi `image_url`)

## 3) Kullanılacak API

Base URL (örnek):

```txt
TRYON_API_BASE_URL=http://localhost:8000
```

Endpointler:

- `POST /api/v1/tryon/composite`
- `POST /api/v1/tryon/composite/stream`  (önerilen)

Header:

```http
Content-Type: application/json
X-API-Key: <TRYON_API_KEY varsa>
```

## 4) Request sözleşmesi (birebir)

```json
{
  "scene_image": "data:image/jpeg;base64,...",
  "product_layers": {
    "base": "https://cdn.shopify.com/s/files/.../advanced-siyah.jpg",
    "yan": null,
    "orta": null,
    "iplik": null,
    "overlay": null
  },
  "product_reference": {
    "title": "Otom Advanced Design Universal Babyface Oto Koltuk Kılıfı",
    "handle": "otom-advanced-design-universal-babyface-oto-koltuk-kilifi",
    "image_url": "https://cdn.shopify.com/s/files/.../advanced-siyah.jpg",
    "shopify_id": "gid://shopify/ProductVariant/...",
    "product_category": "universal_koltuk_kilifi"
  },
  "vehicle_info": {
    "year": "2021",
    "brand": "Audi",
    "model": "A4",
    "vehicle_type": "Sedan",
    "seat_count": 5
  },
  "seat_target": "auto"
}
```

### Alan anlamları

| Alan | Zorunlu | Anlam |
|---|---|---|
| `scene_image` | Evet | Kullanıcının araç içi fotoğrafı (`data:` URL) |
| `product_layers.base` | Evet | Referans ürün görseli (variant CDN URL veya data URL) |
| `product_reference` | Önerilir | Ürün metadata’sı (title/handle/id) |
| `product_reference.image_url` | Önerilir | `product_layers.base` ile **aynı** URL |
| `vehicle_info` | Opsiyonel | Prompt bağlamı |
| `seat_target` | Opsiyonel | Varsayılan `auto` |

Not: Hazır katalog ürünlerinde `yan/orta/iplik/overlay` null kalabilir.
Önemli olan `base`.

## 5) Frontend yönlendirme akışı (chat)

1. Chat’te ürün netleşir (ör. Advanced Babyface / Siyah).
2. Assistant sorar:  
   “Bu ürünün aracınızda nasıl duracağını görmek ister misiniz?”
3. Kullanıcı “evet” der.
4. Frontend araç içi görsel ister (yoksa).
5. Frontend try-on API’ye istek atar.
6. Stream’den `tryon_preview_ready` gelince sonucu chat’te gösterir.

### Stream eventleri

- `status` → loading metni
- `tryon_preview_ready` → `result_image`, `placement_confidence`
- `error` → hata
- `done` → bitti

## 6) Referans ürünü nasıl seçmeli?

Frontend, ürün title’ından görsel uydurmaz.
Referans URL şu endpoint’ten gelir:

```http
GET /api/products/{product_title}/variants
```

Örnek response (kritik alanlar):

```json
{
  "product_title": "Otom Advanced Design Universal Babyface Oto Koltuk Kılıfı",
  "handle": "otom-advanced-design-universal-babyface-oto-koltuk-kilifi",
  "featured_image_url": "https://cdn.shopify.com/.../featured.jpg",
  "variant_count": 5,
  "variants": [
    {
      "id": "gid://shopify/ProductVariant/...",
      "color": "Siyah",
      "title": "Siyah",
      "price": "10000.00",
      "image_url": "https://cdn.shopify.com/.../advanced-siyah.jpg",
      "available_for_sale": true
    }
  ]
}
```

Try-on mapping:

```ts
const selected = variantsResponse.variants.find(v => v.color === chosenColor);

const request = {
  scene_image: userSceneDataUrl,
  product_layers: {
    base: selected.image_url, // KRİTİK — variant image_url
    yan: null,
    orta: null,
    iplik: null,
    overlay: null,
  },
  product_reference: {
    title: variantsResponse.product_title,
    handle: variantsResponse.handle,
    image_url: selected.image_url,
    shopify_id: selected.id,
    product_category: "universal_koltuk_kilifi",
  },
  seat_target: "auto",
};
```

Fallback (yalnızca `image_url` boşsa):

```ts
const imageUrl = selected.image_url || variantsResponse.featured_image_url;
```

## 7) Yapılmaması gerekenler

1. Ürün title’ından görsel üretmeye çalışmak
2. Sadece product-level `featuredImage` kullanmak
3. Variant seçmeden try-on başlatmak
4. `product_layers.base` boş bırakıp sadece `product_reference` göndermek
5. Chat LLM’inin “görsel URL uydurmasını” beklemek

## 8) Hızlı doğrulama checklist

- [ ] Seçilen satırda `image_url` dolu mu?
- [ ] `product_layers.base === product_reference.image_url` mi?
- [ ] `scene_image` `data:image/...;base64,...` mi?
- [ ] İstek `/api/v1/tryon/composite/stream` endpoint’ine mi gidiyor?
- [ ] UI `tryon_preview_ready.result_image` event’ini mi render ediyor?

## 9) Tek cümlelik özet (ekip içi)

> Try-on bağlantısı = kullanıcı araç fotoğrafı + seçilen **variant referans görseli** (`product_layers.base`); frontend görsel çıkarımı yapmaz, hazır URL’yi bu API’ye gönderir.
