import os
from typing import List, Optional
from urllib.parse import urlencode

from src.config import ContentSource
from src.fetchers.base import BaseFetcher, FetchResult, Article
from src.utils.logger import get_logger


class WeatherFetcher(BaseFetcher):
    """QWeather API Fetcher for fetching weather forecasts and generating formatted weather reports."""
    
    type_name = "weather"
    dedup_enabled = False
    src_placeholder = "城市名称，例如: 北京 或 Shanghai"
    config_schema = {
        "metadata.date": {
            "type": "text",
            "label": "预报日期 (date)",
            "placeholder": "today, tomorrow, 2, 或具体日期 YYYY-MM-DD"
        }
    }
    required_secrets = {
        "QWEATHER_KEY": "和风天气 API 密钥，用于获取天气数据。",
        "QWEATHER_HOST": "和风天气 API 主机地址。"
    }
    def __init__(self, source: ContentSource, global_limit: int = 15, max_retries: int = 3):
        super().__init__(source, global_limit=global_limit, max_retries=max_retries)
        
        api_key = os.environ.get("QWEATHER_KEY")
        if not api_key:
            raise ValueError(
                "Required secret 'QWEATHER_KEY' is not set. "
                "Please add it to GitHub Secrets or environment variables."
            )
        self.api_key = api_key
        
        api_host = os.environ.get("QWEATHER_HOST")
        if not api_host:
            raise ValueError(
                "Required secret 'QWEATHER_HOST' is not set. "
                "Please add it to GitHub Secrets or environment variables."
            )
        self.api_host = api_host

    def _request_json(self, path: str, params: dict, what: str) -> dict:
        """Sends HTTP request and returns parsed JSON data."""
        query_string = urlencode(params)
        url = f"https://{self.api_host}{path}?{query_string}"
        headers = {
            "Accept-Encoding": "gzip"
        }
        response = self._make_request(url, headers=headers)
        data = response.json()
        if data.get("code") != "200":
            raise ValueError(f"Error from API ({what}): {data.get('code')} - {data.get('msg', 'Unknown error')}")
        return data

    def _resolve_location(self, city: str):
        """Resolves city name to Location ID using GeoAPI."""
        data = self._request_json(
            "/geo/v2/city/lookup",
            {"location": city, "key": self.api_key, "lang": "zh", "number": 1},
            "geo lookup"
        )
        locations = data.get("location") or []
        if not locations:
            raise ValueError(f"Could not resolve city '{city}' via GeoAPI.")
        first = locations[0]
        return first.get("id"), first.get("name", city)

    def _get_weather_forecast(self, location_id: str):
        """Fetches 3-day weather forecast from QWeather API."""
        data = self._request_json(
            "/v7/weather/3d",
            {"location": location_id, "key": self.api_key, "lang": "zh"},
            "weather"
        )
        return data["daily"]

    def _select_forecast_day(self, daily_forecast, date_param):
        """Selects the specific forecast day based on date_param (defaults to tomorrow/index 1)."""
        if not daily_forecast:
            raise ValueError("No forecast data available.")

        if date_param is None:
            if len(daily_forecast) < 2:
                raise ValueError("Insufficient forecast data (at least 2 days needed for tomorrow default).")
            return daily_forecast[1]

        date_param_str = str(date_param).strip().lower()

        if date_param_str in ("today", "0"):
            return daily_forecast[0]
        elif date_param_str in ("tomorrow", "1"):
            if len(daily_forecast) < 2:
                raise ValueError("Tomorrow's forecast is not available.")
            return daily_forecast[1]
        elif date_param_str == "2":
            if len(daily_forecast) < 3:
                raise ValueError("Day after tomorrow's forecast is not available.")
            return daily_forecast[2]

        for day in daily_forecast:
            if day.get("fxDate") == date_param_str:
                return day

        raise ValueError(f"Could not find forecast for date or index '{date_param}'.")

    def _format_weather(self, day: dict, city_name: str):
        """Formats weather forecast into a clean title and HTML body description."""
        date_str = day.get("fxDate", "N/A")
        sunrise = day.get("sunrise", "N/A")
        sunset = day.get("sunset", "N/A")
        moonrise = day.get("moonrise", "N/A")
        moonset = day.get("moonset", "N/A")
        moon_phase = day.get("moonPhase", "N/A")
        moon_phase_icon = day.get("moonPhaseIcon", "N/A")
        temp_max = day.get("tempMax", "N/A")
        temp_min = day.get("tempMin", "N/A")
        icon_day = day.get("iconDay", "N/A")
        text_day = day.get("textDay", "N/A")
        wind_360_day = day.get("wind360Day", "N/A")
        wind_dir_day = day.get("windDirDay", "N/A")
        wind_scale_day = day.get("windScaleDay", "N/A")
        wind_speed_day = day.get("windSpeedDay", "N/A")
        icon_night = day.get("iconNight", "N/A")
        text_night = day.get("textNight", "N/A")
        wind_360_night = day.get("wind360Night", "N/A")
        wind_dir_night = day.get("windDirNight", "N/A")
        wind_scale_night = day.get("windScaleNight", "N/A")
        wind_speed_night = day.get("windSpeedNight", "N/A")
        humidity = day.get("humidity", "N/A")
        precip = day.get("precip", "N/A")
        vis = day.get("vis", "N/A")
        cloud = day.get("cloud", "N/A")
        uv_index = day.get("uvIndex", "N/A")

        title = f"{city_name}天气 {date_str}: {text_day}, {temp_min}°C - {temp_max}°C"
        description = (
            "<div>"
            f"白天天气：{text_day}（图标：{icon_day}）<br>"
            f"夜间天气：{text_night}（图标：{icon_night}）<br>"
            f"温度：{temp_min}°C 至 {temp_max}°C<br>"
            f"降水量：{precip} mm<br>"
            f"云量：{cloud}%<br>"

            f"湿度：{humidity}%<br><br>"
            f"白天风力：{wind_dir_day}（{wind_360_day}°），{wind_scale_day}级，风速 {wind_speed_day} km/h<br>"
            f"夜间风力：{wind_dir_night}（{wind_360_night}°），{wind_scale_night}级，风速 {wind_speed_night} km/h<br><br>"

            f"能见度：{vis} km<br>"
            f"日出/日落：{sunrise} / {sunset}<br>"
            f"月出/月落：{moonrise} / {moonset}（月相：{moon_phase}，{moon_phase_icon}）<br>"
            f"紫外线指数：{uv_index}"
            "</div>"
        )
        return title, description

    def fetch(self) -> FetchResult:
        result = FetchResult(source=self.source, articles=[])
        try:
            city = self.source.src
            # 1. Resolve city
            location_id, city_name = self._resolve_location(city)
            self.logger.info(f"Resolved city '{city}' -> {city_name} (ID: {location_id})")

            # 2. Get weather forecast
            forecast_data = self._get_weather_forecast(location_id)

            # 3. Select forecast day
            metadata = self.source.metadata or {}
            date_param = metadata.get("date")
            day_forecast = self._select_forecast_day(forecast_data, date_param)

            # 4. Generate title and description HTML
            title, description = self._format_weather(day_forecast, city_name)

            # 5. Create article
            article = Article(
                title=title,
                content=description,
                url=day_forecast.get("fxDate"),
                published_date=day_forecast.get("fxDate"),
                author="QWeather",
                metadata={"city": city_name, "location_id": location_id}
            )

            if not self._should_delete(article.title):
                result.articles.append(article)
                result.source_title = f"{city_name}天气预报"

            return result
        except Exception as e:
            self.logger.error(f"Weather fetch failed: {e}")
            result.success = False
            result.error = str(e)
            return result
