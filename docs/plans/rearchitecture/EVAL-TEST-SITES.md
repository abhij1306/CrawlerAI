# Eval & test-site reference corpus

Provided by the repo owner as the reference set for extraction correctness and
for exercising the LEARN-ONCE recipe tier against real sites.

- **Human-verified "good output" labels** live in `backend/eval/labels/commerce_detail/<result_id>.json`
  (schema `extraction_v3_label.v1`: top-level `url`, `surface`, `fields`, `variants`,
  `human_verified`, operator `metadata`/`verification_notes`). These are the ground truth a
  learned recipe's replayed records should reproduce. Pair each with its captured HTML fixture
  under `backend/eval/fixtures/commerce_detail/` before scoring with `backend/eval/`.
- **Test-site URLs** below are grouped by surface: Section S (commerce sandboxes), Section CE
  (commerce detail — extended, real retailers), Section LC (listing commerce), Section LJ
  (listing jobs). Use sandboxes for deterministic CI-safe checks and the real retailers for
  drift/grounding validation.

---

## Section S — Commerce Sandboxes

https://web-scraping.dev/product/1
https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
https://books.toscrape.com/catalogue/page-1.html
https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
https://web-scraping.dev/products
https://web-scraping.dev/product/1
https://scrapingcourse.com/ecommerce/
https://scrapingcourse.com/ecommerce/products/chaz-kangeroo-hoodie
https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops
https://sandbox.oxylabs.io/products
https://sandbox.oxylabs.io/products/1
https://webscraper.io/test-sites/e-commerce/ajax/computers/laptops
https://webscraper.io/test-sites/e-commerce/scroll/computers/laptops
https://practicesoftwaretesting.com
https://practicesoftwaretesting.com/product/01HB
https://books.toscrape.com/
https://webscraper.io/test-sites/e-commerce/scroll/computers/laptops
https://www.myntra.com/hand-towels
https://in.puma.com/in/en/mens/mens-shoes/mens-shoes-sneakers

https://www.adidas.com
https://www.zara.com
https://www.hm.com
https://www.uniqlo.com
https://www.levi.com
https://www.underarmour.com
https://www.puma.com
https://www.newbalance.com
https://www.skechers.com
https://www.crocs.com
https://www.gap.com
https://www.thenorthface.com
https://www.columbia.com
https://www.tommy.com
https://www.calvinklein.us
https://www.ralphlauren.com
https://www.vans.com
https://www.lululemon.com
https://www.louisvuitton.com
https://www.gucci.com
https://www.dior.com
https://www.hermes.com
https://www.rolex.com
https://www.cartier.com
https://www.tiffany.com
https://www.sephora.com
https://www.maccosmetics.com
https://www.loreal.com
https://www.esteelauder.com
https://www.dove.com
https://www.gillette.com
https://www.clinique.com
https://www.bk.com
https://www.chipotle.com
https://www.dunkindonuts.com
https://www.lego.com
https://www.bestbuy.com
https://www.ebay.com
https://www.etsy.com
https://www.wayfair.com
https://www.macys.com
https://www.nordstrom.com
https://www.williams-sonoma.com
https://www.potterybarn.com
https://www.bedbathandbeyond.com
https://www.cvs.com
https://www.walgreens.com
https://www.dickssportinggoods.com
https://www.lululemon.com
https://www.anthropologie.com
https://www.freepeople.com
https://www.urbanoutfitters.com
https://www.jcrew.com
https://www.madewell.com
https://www.abercrombie.com
https://www.hollisterco.com
https://www.ae.com
https://www.pacsun.com
https://www.asos.com
https://www.shein.com
https://www.temu.com
https://www.aliexpress.com
https://www.chewy.com
https://www.petco.com
https://www.petsmart.com
https://www.ulta.com
https://www.bathandbodyworks.com
https://www.victoriassecret.com
https://www.asics.com
https://www.timberland.com
https://www.docmartens.com
https://www.stevemadden.com
https://www.aldoshoes.com
https://www.michaelkors.com
https://www.coach.com
https://www.katespade.com
https://www.toryburch.com
https://www.burberry.com
https://www.prada.com
https://www.fendi.com
https://www.balenciaga.com
https://www.armani.com

## Section LJ — Listing Jobs
https://www.usajobs.gov/search/results/?k=software+engineer&p=1
https://www.governmentjobs.com/careers/california
https://www.higheredjobs.com/admin/search.cfm?JobCat=108
https://www.idealist.org/en/jobs
https://boards.greenhouse.io/embed/job_board?for=airbnb
https://boards.greenhouse.io/embed/job_board?for=shopify
https://boards.greenhouse.io/embed/job_board?for=discord
https://boards.greenhouse.io/embed/job_board?for=palantir
https://startup.jobs/
https://jobs.80000hours.org/jobs
https://cryptocurrencyjobs.co/
https://euremotejobs.com/
https://dynamitejobs.com/remote-jobs
https://jobicy.com/
https://www.instahyre.com/search-jobs
https://www.vc5partners.com/jobs/
https://www.klingspor.com/jobs
https://careers.clarkassociatesinc.biz/
https://atlasmedstaff.com/job-search/
https://ehccareers-emory.icims.com/jobs/search?pr=0&searchRelation=keyword_all
https://www.paycomonline.net/v4/ats/web.php/portal/8EC14E985B45C7F52C531F487F62A2B8/career-page
https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/?q=&o=postedDateDesc
https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=14fa7571-bfac-427f-aa18-9488391d4c5e&ccId=19000101_000001&type=MP&lang=en_US&selectedMenuKey=CurrentOpenings
https://smithnephew.wd5.myworkdayjobs.com/External
https://ats.rippling.com/en-GB/inhance-technologies/jobs
https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location


## Section LC — Listing Commerce

https://www.abebooks.com/servlet/SearchResults?kn=python&pt=book
https://www.thriftbooks.com/browse/?b.search=science
https://www.uline.com/BL_8421/Boxes
https://www.ifixit.com/Parts
https://www.rockler.com/wood/exotic-lumber
https://www.reverb.com/marketplace?product_type=electric-guitars
https://www.discogs.com/sell/list?genre=Electronic
https://www.musiciansfriend.com/snare-drum-heads
https://www.autozone.com/filters-and-pcv/oil-filter
https://www.chewy.com/b/dry-dog-food-294
https://www.thomann.de/gb/guitars.html
https://www.govplanet.com/for-sale/equipment
https://www.kitchenaid.com/countertop-appliances/food-processors/food-processor-and-chopper-products
https://www.desertcart.in/search?query=Nutrition+%26+Healthy+Eating
https://www.firstcry.com/sets-and--suits/6/166?scat=166&gender=girl,unisex&ref2=menu_dd_girl-fashion_sets-and-suits_H
https://www.backmarket.com/en-us/l/iphone/e8724fea-197e-4815-85ce-21b8068020cc
https://www.dyson.in/vacuum-cleaners/cord-free
https://www.grailed.com/categories/womenswear/blazers
https://www.stadiumgoods.com/collections/adidas-shoes
https://www2.hm.com/en_in/men/shoes/view-all.html
https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html?trksrc=navbar&trkid=l2
https://zadig-et-voltaire.com/eu/uk/c/tshirts-sweatshirts-for-men-127
https://31philliplim.com/collections
https://ar.puma.com/lo-mas-vendido
https://www.karenmillen.com/eu/categories/womens-trousers
https://www.ganni.com/en-gb/trainers/
https://www.phase-eight.com/clothing/dresses/
https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos
https://savannahs.com/collections/all-boots
https://arcteryx.com/ca/en/c/mens/footwear-run/wid-kjyr4dq9?intcmp=c-mens-footwear-climb-wid-kjyr4dq9_t2_c-mens-footwear-run-wid-kjyr4dq9
https://www.intimissimi.com.br/masculino/vestuario/camiseta-manga-comprida?O=OrderByReleaseDateDESC&page=1
https://www.calvinklein.com.br/masculino/underwear/kits-de-cueca
https://www.midea.com.br/eletroportateis/chaleira-eletrica?category-1=eletroportateis&category-2=chaleira-eletrica&fuzzy=0&operator=and&facets=category-1%2Ccategory-2%2Cfuzzy%2Coperator&sort=score_desc&page=0

## Section CE — Commerce Extended

https://stockx.com/nike-dunk-low-retro-white-black-2021
https://www.grailed.com/listings/92502018-peter-do-velcro-strap-set-up-blazer-pants?g_aidx=Listing_by_listing_quality_production&g_aqid=dcff41da6c7483961c0b500769d4c7bc
https://www.sneakersnstuff.com/products/dime-soft-rock-crewneck-dime2sp2542blk
https://sneakerpolitics.com/collections/hoodies/products/one-of-these-days-follow-the-road-pullover-hoodie-dark-brown
https://www.shoepalace.com/products/jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1?variant=43468991627470
https://www.dtlr.com/collections/men/products/jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103
https://www.endclothing.com/us/47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html?queryID=92cd67a81343c72b1e7ea4257417a975
https://www.size.co.uk/product/purple-adidas-originals-sl-72-pt/19738059/
https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000
https://www.backmarket.com/en-us/p/iphone-15-plus
https://www.target.com/p/tobago-stripe-duvet-cover-set-levtex-home/-/A-1002150739?preselect=1002150742#lnk=sametab
https://www.nordstrom.com/s/nike-air-force-1-07-basketball-sneaker-men/7507996
https://www.birkenstock.com/us/arizona-birko-flor/arizona-core-birkoflor-0-eva-u_1.html
https://www.converse.com/shop/p/chuck-taylor-all-star-retro-embroidery-unisex-high-top-shoe/A16914F.html?dwvar_A16914F_color=black%2Fnew%20found%20bloom&dwvar_A16914F_width=standard&styleNo=A16914F&cgid=womens-high-top-shoes
https://us.frankbody.com/products/original-coffee-scrub
https://colourpop.com/products/going-coconuts-eyeshadow-palette
https://bombas.com/products/mens-all-purpose-performance-ankle-socks
https://www.vans.com/en-us/p/shoes/icons/old-skool-5205/old-skool-VN000E9TBPG
https://www.puravidabracelets.com/products/black-seascape-stretch-bracelet?pr_prod_strat=e5_desc&pr_rec_id=3ef961ba9&pr_rec_pid=7216396632150&pr_ref_pid=7559267778646&pr_seq=uniform&variant=41298450153558
https://31philliplim.com/collections/the-luna-bag-1/products/luna-1
https://savannahs.com/collections/all-boots/products/pavlova-100-lace-up-blush-satin-boots-cl28517s
https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111
https://www.adidas.com/us/stan-smith-shoes/M20324.html
https://in.puma.com/in/en/pd/speedcat-sneakers/406329?swatch=02
https://ar.puma.com/pd/zapatillas-mostro-ecstasy-unisex/397328.html?color=07
https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html?v1=527078510
https://www.gymshark.com/products/gymshark-arrival-5-shorts-black-ss22
https://www.fashionnova.com/products/just-vibes-strapless-pant-set-yellow?recommendationAttributionId=error-nosto-1-fallback-nosto-1-copy-1720644688978
https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035
https://www.zappos.com/kratos/p/womens-hoka-bondi-9-berry-jam-berry-patch/product/9984296/color/318988?zlfid=191&ref=pd_search_nr-1-bqcp_1
https://www.asos.com/us/asos-curve/asos-design-curve-lightweight-pull-on-barrel-pants-in-darkwash/prd/210397084#colourWayId-210397088
https://zadig-et-voltaire.com/eu/uk/p/JMTS01771443/t-shirt-teddyx-blue-sixtine
https://www.karenmillen.com/eu/product/karen-millen-cotton-utility-button-detail-barrel-leg-trouser_bkk28382?colour=ivory
https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html
https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos/products/italian-seersucker-sutton-suit-2
https://www.glossier.com/en-in/products/balm-dotcom
https://www.brooklinen.com/products/plush-bath-towels?variant=42851068870746
https://www.apple.com/shop/buy-iphone/iphone-16
https://www.ssense.com/en-us/men/product/willy-chavarria/brown-ruff-rider-leather-jacket/19072301
https://www.selfridges.com/GB/en/product/creed-aventus-eau-de-parfum_365-83022651-AVENTUS/
https://www.mytheresa.com/int/en/women/valentino-garavani-loco-small-floral-linen-top-handle-bag-beige-p01155657
https://www.mrporter.com/en-us/mens/product/cartier-eyewear/accessories/aviator/pasha-aviator-style-silver-tone-sunglasses/46376663163032937
https://www.net-a-porter.com/en-us/shop/product/eleuteri/jewelry-and-watches/vintage-bracelets/plus-bulgari-vintage-1980s-doppio-cuore-18-karat-gold-coral-and-diamond-bracelet/46376663163120086
https://www.luisaviaroma.com/en-in/p/barrow/kids-boys/83I-UKD027?ColorId=MDgw0&lvrid=_p_dBRW_gkb
https://www.gucci.com/int/en/pr/men/accessories-for-men/scarves-for-men/scarves-for-men/gg-wool-silk-jacquard-stole-p-8705434GAK31360
https://www.onepeloton.com/shop/tread
https://www.rockler.com/rockler-table-saw-crosscut-sled
https://www.ifixit.com/products/iphone-16-plus-battery
https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail
https://www.dickssportinggoods.com/p/birkenstock-womens-arizona-big-buckle-soft-footbed-sandals-25birwcasuwrznbgbcegp/25birwcasuwrznbgbcegp?color=Sandcastle
https://www.jdsports.co.uk/product/pink-adidas-originals-classic-shorts/19741988/
https://www.decathlon.co.uk/p/pressurised-padel-balls-pb-speed-tri-pack/347273/m8804642
https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html
https://www.williams-sonoma.com/products/breville-the-bambino-plus/
https://intl.fender.com/products/american-vintage-ii-1972-telecaster-thinline?variant=45940647035102
https://www.nintendo.com/us/store/products/pragmata-switch-2/
https://www.usa.canon.com/shop/p/eos-r5
https://www.lego.com/en-us/product/millennium-falcon-75192
https://www.sony.co.in/interchangeable-lens-cameras/products/ilce-9m3?sku=ilce-9m3-in5
https://fellowproducts.com/products/stagg-ekg-electric-pour-over-kettle
https://www.roamluggage.com/collections/luggage/products/large-check-in
https://www.therevolverclub.com/products/technics-sl-1200mk7?variant=39337238593654&country=IN%C2%A4cy=INR&srsltid=AfmBOorhNg50VFVA7JuwiVt-GvpmZo20096mRBth-CNZwRVTLnvRD8Asy5Q
https://www.bluenile.com/engagement-rings/design-your-own-ring/classic-four-prong-solitaire-engagement-ring-in-platinum-item-194156
https://www.aesop.com/home-fragrance/candles/aganice-aromatique-candle/HM03.html#tab=description
https://www.amazon.com/Sparkling-Prebiotic-Beverage-Vinegar-Seltzer/dp/B0F5Y3X8PP/?th=1
https://amsterdamvintagewatches.com/shop/rolex-day-date-18038-champagne-5/
https://www.bhphotovideo.com/c/product/1882297-REG/cozyla_cd_8v543f0_white_us_32_4k_calendar_gen2_white.html
https://arcteryx.com/ca/en/shop/mens/norvan-ld-4-gtx-shoe-0397
https://www.bluenile.com/engagement-rings/design-your-own-ring/riviera-pave-diamond-engagement-ring-in-14k-white-gold-1-6-ct-tw-item-195326
https://www.brilliantearth.com/Secret-Halo-1.5mm-Diamond-Ring-14K-Gold-BE1D13065-76823478

https://www2.hm.com/en_us/productpage.1344928003.html
https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html
https://www.uniqlo.com/us/en/products/E455957-000/00?colorDisplayCode=57&sizeDisplayCode=004
https://www.levi.com/US/en_US/clothing/men/shorts/carrier-cargo-lightweight-9-mens-shorts/p/001KG0053
https://www.underarmour.com/en-us/p/ua_charged_assert_10_mens_running_shoes/3026175.html
https://us.puma.com/us/en/pd/suede-classic-sneakers/395205
https://www.newbalance.com/pd/1080v15/M1080V15_RU-FTW-825428.html?dwvar_M1080V15__RU-FTW-825428_style=M108022W
https://www.thenorthface.com/en-us/p/womens/womens-bottoms/womens-pants-224272/womens-basin-convertible-pants-NF0A8FBT?color=2EL
https://www.gap.com/browse/product.do?pid=887835012&vid=1&pcid=80799&cid=80799&nav=meganav%3AMen%3ACategories%3APants#pdp-page-content
https://www.skechers.com/skechers-viper-court-pro-2.0---pickleball/246109_WBLP.html
https://us.louisvuitton.com/eng-us/products/bootleg-pants-nvprod7220319v/1AJUPQ
https://shop.lululemon.com/p/jackets-and-hoodies-jackets/Nulu-Cropped-Define-Jacket/_/prod10930188?color=77142
https://www.calvinklein.us/en/men/accessories/bags/structured-commuter-bag/198629014314.html
https://www.ralphlauren.global/in/en/the-iconic-cotton-chino-ball-cap-650310.html?dwvar650310_colorname=Heritage%20Royal&cgid=women-scarves-hats-gloves#start=1&cgid=women-scarves-hats-gloves
https://www.columbia.com/p/womens-chill-river-midi-dress-1933601.html?color=606
https://usa.tommy.com/en/women/shoes-accessories/shoes/script-monogram-espadrille-sandal/TZ001658-420.html?journey=women-shoesandacc-shoes-sandalsandslides
https://www.vans.com/en-us/p/shoes/icons/old-skool-5205/lx-old-skool-36-VN000D9RH91
https://www.sephora.com/product/eadem-le-chouchou-exfoliating-softening-peptide-lip-balm-P511921?skuId=2960730&icid2=bestsellers_us_skugrid_ufe:p511921:product
https://www.clinique.com/product/1687/126187/skincare/moisturizers/clinique-smart-clinical-repairtm-overnight-recovery-cream-mask
https://www.maccosmetics.com/product/13840/363/products/makeup/eyes/eyeshadow/eye-shadow
https://www.balmainbeauty.com/product/39323/130117/fragrance/carbone-eau-de-parfum#/sku/189322
https://www.jcrew.com/in/m/womens/categories/clothing/pants/wide-leg/ME988?display=standard&fit=Classic&colorProductCode=CI939&colorCode=BR8825
https://www.ae.com/us/en/p/women/tops/tank-tops-tube-tops/ae-daily-fave-tank-top/0366_6514_115
https://www.chewy.com/wellness-core-rawrev-grain-free-wild/dp/141791
https://www.petco.com/product/blue-female-crowntail-betta