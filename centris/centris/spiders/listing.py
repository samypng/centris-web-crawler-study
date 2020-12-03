import json

import scrapy
from scrapy.selector import Selector
from scrapy_splash import SplashRequest


class ListingSpider(scrapy.Spider):
    name = 'listing'
    allowed_domains = ['www.centris.ca']
    positions = {"startPosition": 0}
    http_user = "user"
    http_pass = "userpass"

    script = """
        function main(splash, args)
          splash.images_enabled = false
          splash.js_enabled = false
          splash:on_request(function(request)
            if request.url:find('css') then
                request.abort()
            end
          end)
          assert(splash:go(args.url))
          assert(splash:wait(0.5))
          return splash:html()
        end
    """

    def start_requests(self):
        yield scrapy.Request(
            url='https://www.centris.ca/UserContext/Lock',
            method='POST',
            headers={
                'x-requested-with': 'XMLHttpRequest',
                'content-type': 'application/json'
            },
            body=json.dumps({'uc': 0}),
            callback=self.generate_uck
        )

    def generate_uck(self, response):
        uck = str(response.body, "utf-8")
        yield response.follow("https://www.centris.ca/en?uc=0", meta={"uck": uck}, callback=self.update_query)

    def update_query(self, response):
        query = {
            "query": {
                "UseGeographyShapes": 0,
                "Filters": [
                    {
                        "MatchType": "GeographicArea",
                        "Text": "Montréal (Island)",
                        "Id": "GSGS4621"
                    }
                ],
                "FieldsValues": [
                    {
                        "fieldId": "GeographicArea",
                        "value": "GSGS4621",
                        "fieldConditionId": "",
                        "valueConditionId": ""
                    },
                    {
                        "fieldId": "Category",
                        "value": "Residential",
                        "fieldConditionId": "",
                        "valueConditionId": ""
                    },
                    {
                        "fieldId": "SellingType",
                        "value": "Sale",
                        "fieldConditionId": "",
                        "valueConditionId": ""
                    },
                    {
                        "fieldId": "LandArea",
                        "value": "SquareFeet",
                        "fieldConditionId": "IsLandArea",
                        "valueConditionId": ""
                    },
                    {
                        "fieldId": "SalePrice",
                        "value": 0,
                        "fieldConditionId": "ForSale",
                        "valueConditionId": ""
                    },
                    {
                        "fieldId": "SalePrice",
                        "value": 999999999999,
                        "fieldConditionId": "ForSale",
                        "valueConditionId": ""
                    }
                ]
            },
            "isHomePage": True
        }
        yield scrapy.Request(url="https://www.centris.ca/property/UpdateQuery",
                             method="POST",
                             body=json.dumps(query),
                             headers={
                                 'Content-Type': 'application/json',
                                 'x-requested-with': 'XMLHttpRequest',
                                 'x-centris-uc': 0,
                                 'x-centris-uck': response.meta['uck']
                             },
                             meta={"uck": response.meta['uck']},
                             callback=self.get_inscriptions)

    def get_inscriptions(self, response):
        yield scrapy.Request(url="https://www.centris.ca/Property/GetInscriptions",
                             method="POST",
                             body=json.dumps(self.positions),
                             headers={
                                 'Content-Type': 'application/json',
                                 'x-requested-with': 'XMLHttpRequest',
                                 'x-centris-uc': 0,
                                 'x-centris-uck': response.meta['uck']
                             },
                             meta={"uck": response.meta['uck']},
                             callback=self.parse)

    def parse(self, response):
        parsed_data = json.loads(response.body)
        html = parsed_data['d']['Result']['html']
        sel = Selector(text=html)
        listings = sel.xpath("//div[@data-id='templateThumbnailItem']")
        for listing in listings:
            category = listing.xpath("normalize-space(.//div[@class='location-container']/span/div/text())").get()
            category = category[:category.find("\xa0")] if category else ""
            features = self.handle_features(
                listing.xpath(".//div[@class='d-flex justify-content-start flex-wrap features']"))
            price = listing.xpath(".//span[@itemprop='price']/@content").get()
            city = listing.xpath(".//span[@class='address']/div[2]/text()").get()
            url = listing.xpath(".//div/a[@class='a-more-detail']/@href").get()
            abs_url = f"https://www.centris.ca{url}"

            yield SplashRequest(url=abs_url,
                                callback=self.parse_summary,
                                endpoint='execute',
                                args={
                                    'lua_source': self.script
                                },
                                meta={
                                    "category": category,
                                    "features": features,
                                    "price": price,
                                    "city": city,
                                    "url": abs_url
                                })

        count = parsed_data['d']['Result']['count']
        increment_number = parsed_data['d']['Result']['inscNumberPerPage']
        if self.positions['startPosition'] <= count:
            self.positions['startPosition'] += increment_number
            yield scrapy.Request(url="https://www.centris.ca/Property/GetInscriptions",
                                 method="POST",
                                 body=json.dumps(self.positions),
                                 headers={
                                     'Content-Type': 'application/json',
                                     'x-requested-with': 'XMLHttpRequest',
                                     'x-centris-uc': 0,
                                     'x-centris-uck': response.meta['uck']
                                 },
                                 meta={"uck": response.meta['uck']},
                                 callback=self.parse)

    def parse_summary(self, response):
        category = response.meta['category']
        features = response.meta['features']
        price = response.meta['price']
        city = response.meta['city']
        url = response.meta['url']
        address = response.xpath("//h2[@itemprop='address']/text()").get()
        description = response.xpath("normalize-space(//div[@itemprop='description']/text())").get()
        yield {
            "category": category,
            "features": features,
            "price": price,
            "city": city,
            "url": url,
            "address": address,
            "description": description
        }

    def handle_features(self, element):
        rooms = element.xpath(".//div[@class='cac']/text()").get()
        rooms = rooms if rooms else 0
        bathroom = element.xpath(".//div[@class='sdb']/text()").get()
        bathroom = bathroom if bathroom else 0
        return f"{rooms} Beds, {bathroom} baths"
