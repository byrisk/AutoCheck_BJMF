# app/services/location_engine.py
import os
import yaml # LocationEngine 使用了 yaml
import re   # LocationEngine 使用了 re
import math # LocationEngine 使用了 math
import random # LocationEngine 使用了 random
import difflib # LocationEngine 使用了 difflib
import requests # LocationEngine 的 get_map_link 使用了 requests
from typing import Dict, List, Optional, Tuple, Any # TypedDict 在 config.models 中

# 从 app.constants 导入 AppConstants
from app.constants import AppConstants
# 从 app.logger_setup 导入 LoggerInterface 和 LogLevel
from app.logger_setup import LoggerInterface, LogLevel
# 从 app.config.models 导入 HotSpotData, SelectedSchoolData (这些是类型定义)
from app.config.models import HotSpotData, SelectedSchoolData
# 从 app.exceptions 导入自定义异常
from app.exceptions import ConfigError, LocationError
# 从 app.utils.app_utils 导入 get_app_dir (LocationEngine 用它来确定数据文件路径)
from app.utils.app_utils import get_app_dir

class LocationEngine:

    """Handles loading school data and generating sign-in locations."""
    def __init__(self, logger: LoggerInterface, school_data_file_rel_path: str = AppConstants.SCHOOL_DATA_FILE): # 参数名改为 rel_path
        self.logger = logger
        base_app_path = get_app_dir()
        self.school_data_file = os.path.join(base_app_path, school_data_file_rel_path) # 确保使用的是这个构建好的路径
        self.logger.log(f"LocationEngine: 校区数据文件目标绝对路径: {self.school_data_file}", LogLevel.DEBUG)
        self.all_schools: List[SelectedSchoolData] = []
        self.schools_by_id: Dict[str, SelectedSchoolData] = {}
        try:
            self._load_school_data()
        except ConfigError as e:
             self.logger.log(f"初始化LocationEngine失败 (配置错误): {e}", LogLevel.ERROR)
             # Allow initialization but engine will be non-functional
        except Exception as e:
             self.logger.log(f"初始化LocationEngine时发生未知严重错误: {e}", LogLevel.CRITICAL)
             # Allow initialization but engine will be non-functional

    def _load_school_data(self) -> None:
        """Loads and validates school data from the YAML file."""
        self.logger.log(f"开始加载校区数据文件: {self.school_data_file}", LogLevel.DEBUG)
        try:
            if not os.path.exists(self.school_data_file):
                self.logger.log(f"校区数据文件未找到: {self.school_data_file}。学校选择功能将不可用。", LogLevel.WARNING)
                return # File not found is not a critical error for startup

            with open(self.school_data_file, 'r', encoding='utf-8') as f:
                raw_data = yaml.safe_load(f)

            if not isinstance(raw_data, list):
                raise ConfigError(f"校区文件 '{self.school_data_file}' 顶层结构应为列表 (List)")

            processed_schools: List[SelectedSchoolData] = []
            temp_schools_by_id: Dict[str, SelectedSchoolData] = {}
            seen_ids = set()

            for index, item in enumerate(raw_data):
                entry_num = index + 1
                if not isinstance(item, dict):
                    self.logger.log(f"校区文件条目 {entry_num} 不是有效的字典，已跳过。", LogLevel.WARNING)
                    continue

                school_id_raw = item.get("id", f"missing_id_{entry_num}")
                school_id = str(school_id_raw).strip().lower() # Standardize to lower case
                addr = str(item.get("addr", "")).strip()
                range_data = item.get("range")
                hot_spots_raw = item.get("hot_spots")

                # --- Validate ID format ---
                if not re.fullmatch(r's\d{5}', school_id):
                    self.logger.log(f"校区文件条目 {entry_num} 的 ID '{school_id_raw}' 格式不正确 (应为s+5位数字)，已跳过。", LogLevel.WARNING)
                    continue
                if school_id in seen_ids:
                    self.logger.log(f"校区文件条目 {entry_num} 的 ID '{school_id}' 重复，已跳过。", LogLevel.WARNING)
                    continue

                # --- Validate address ---
                if not addr:
                    self.logger.log(f"校区文件条目 {entry_num} (ID: {school_id}) 缺少 'addr' 字段，已跳过。", LogLevel.WARNING)
                    continue

                # --- Validate range ---
                range_float: Optional[List[float]] = None
                if isinstance(range_data, list) and len(range_data) == 4:
                    try:
                        range_float = [float(x) for x in range_data]
                        # Basic range validation
                        if not (-90 <= range_float[0] <= 90 and -90 <= range_float[1] <= 90 and
                                -180 <= range_float[2] <= 180 and -180 <= range_float[3] <= 180 and
                                range_float[0] <= range_float[1] and range_float[2] <= range_float[3]): # Min <= Max check
                             raise ValueError("经纬度范围值无效或顺序错误")
                    except (ValueError, TypeError) as e:
                         self.logger.log(f"校区文件条目 {entry_num} (ID: {school_id}) 'range' 数据无效 ({e})，已跳过。", LogLevel.WARNING)
                         continue # Skip this entry if range is invalid
                else:
                     self.logger.log(f"校区文件条目 {entry_num} (ID: {school_id}) 'range' 数据缺失或格式错误 (应为4个数字的列表)，已跳过。", LogLevel.WARNING)
                     continue # Skip this entry if range is missing/invalid

                # --- Process hot_spots (optional) ---
                processed_hot_spots: Optional[List[HotSpotData]] = None
                if isinstance(hot_spots_raw, list) and hot_spots_raw:
                    valid_hot_spots_for_entry: List[HotSpotData] = []
                    for hs_idx, hs_item in enumerate(hot_spots_raw):
                        hs_num = hs_idx + 1
                        if isinstance(hs_item, dict):
                            try:
                                name = str(hs_item["name"]).strip()
                                lat = float(hs_item["lat"])
                                lng = float(hs_item["lng"])
                                acc = float(hs_item.get("accuracy", AppConstants.DEFAULT_ACCURACY))
                                weight = int(hs_item.get("weight", 1))
                                if not name: raise ValueError("热点名称不能为空")
                                if not (-90 <= lat <= 90 and -180 <= lng <= 180): raise ValueError("热点经纬度超出范围")
                                if acc <= 0: raise ValueError("热点精度必须为正数")
                                if weight <= 0: weight = 1 # Ensure positive weight

                                # Optional check: hot spot within range
                                if not (range_float[0] <= lat <= range_float[1] and range_float[2] <= lng <= range_float[3]):
                                     self.logger.log(f"学校 {school_id} 的热点 '{name}' (条目 {hs_num}) 不在指定的 range 内，已忽略此热点。", LogLevel.WARNING)
                                     continue

                                valid_hot_spots_for_entry.append({
                                    "name": name, "lat": lat, "lng": lng,
                                    "accuracy": acc, "weight": weight
                                })
                            except (KeyError, ValueError, TypeError) as e:
                                self.logger.log(f"学校 {school_id} 的第 {hs_num} 个热点数据错误 ({e})，已跳过此热点。", LogLevel.WARNING)
                        else:
                             self.logger.log(f"学校 {school_id} 的第 {hs_num} 个热点不是有效的字典，已跳过。", LogLevel.WARNING)
                    if valid_hot_spots_for_entry:
                        processed_hot_spots = valid_hot_spots_for_entry

                # --- Store valid school data ---
                school_data: SelectedSchoolData = {
                    "id": school_id,
                    "addr": addr,
                    "range": range_float, # Store validated float list
                    "hot_spots": processed_hot_spots
                }
                processed_schools.append(school_data)
                temp_schools_by_id[school_id] = school_data
                seen_ids.add(school_id)

            self.all_schools = processed_schools
            self.schools_by_id = temp_schools_by_id
            self.logger.log(f"成功加载并验证 {len(self.all_schools)} 个学校数据。", LogLevel.INFO)

        except yaml.YAMLError as e:
            # Raise a specific error for calling code to handle
            raise ConfigError(f"解析校区文件 '{self.school_data_file}' 失败: {e}") from e
        except Exception as e:
            # Catch any other unexpected error during loading
            self.logger.log(f"加载校区数据时发生未知严重错误: {e}", LogLevel.CRITICAL)
            raise ConfigError(f"加载校区文件时发生未知错误: {e}") from e


    def get_school_by_id(self, school_id: str) -> Optional[SelectedSchoolData]:
        """Get school data by its exact ID (case-insensitive)."""
        return self.schools_by_id.get(school_id.lower())

    def search_schools(self, query: str) -> List[SelectedSchoolData]:
        """Searches schools by ID (exact), name/keywords (contains), and fuzzy match."""
        results: List[SelectedSchoolData] = []
        query_lower = query.strip().lower()

        if not query:
            return [] # Return empty if query is empty

        # 1. Try Exact ID Match First (case-insensitive)
        if re.fullmatch(r's\d{5}', query_lower):
            school = self.get_school_by_id(query_lower)
            if school:
                # If exact ID matches, prioritize it and maybe return only this one?
                # Or add it first, then add others? Let's add it first.
                results.append(school)
                # Optimization: If user provided an exact valid ID, maybe they don't want other results?
                # Consider returning just [school] here if that's the desired UX.
                # For now, we continue searching to find potential name matches too.

        # 2. Keyword 'Contains' Match
        keywords = [kw for kw in query_lower.split() if kw]
        keyword_matches = []
        if keywords:
            for school in self.all_schools:
                 addr_lower = school['addr'].lower()
                 # Ensure this school wasn't already added via ID match
                 if school['id'] not in {s['id'] for s in results}:
                     if all(keyword in addr_lower for keyword in keywords):
                         keyword_matches.append(school)
            results.extend(keyword_matches)

        # 3. Fuzzy Match on Address (if few/no keyword matches or as supplement)
        # Only run fuzzy if keyword search yielded few results or query wasn't an ID
        run_fuzzy = True # Always run for now, can be optimized later
        fuzzy_matches = []
        if run_fuzzy:
            addr_list = [school['addr'] for school in self.all_schools]
            try:
                 # Use original query for fuzzy matching (case might matter slightly for difflib)
                 close_matches_addr = difflib.get_close_matches(query.strip(), addr_list, n=5, cutoff=0.5) # Adjust n and cutoff as needed
            except Exception as e:
                 self.logger.log(f"地址模糊匹配时出错: {e}", LogLevel.WARNING)
                 close_matches_addr = []

            if close_matches_addr:
                for school in self.all_schools:
                    # Ensure this school wasn't already added
                    if school['id'] not in {s['id'] for s in results}:
                        if school['addr'] in close_matches_addr:
                            fuzzy_matches.append(school)
                results.extend(fuzzy_matches)

        # 4. De-duplicate results based on ID
        final_results_dict: Dict[str, SelectedSchoolData] = {}
        for school in results:
            final_results_dict[school['id']] = school

        # Return sorted list (e.g., by ID)
        return sorted(final_results_dict.values(), key=lambda s: s['id'])


    def generate_location(self, school: SelectedSchoolData) -> Dict[str, Any]:
        """Generates recommended coordinates based on school data (hotspots > range > offset)."""
        if not isinstance(school, dict) or not school.get('range'):
            raise LocationError(f"无效或不完整的学校数据用于生成坐标: ID={school.get('id', 'N/A')}")

        base_lat: float = 0.0
        base_lng: float = 0.0
        # Use default accuracy first, override if hotspot selected
        accuracy: float = float(AppConstants.DEFAULT_ACCURACY)
        from_source: str = "未知来源"
        hot_spots = school.get('hot_spots')
        range_data = school['range'] # Assumed valid float list here

        chosen_hot_spot: Optional[HotSpotData] = None
        # Step A: Try selecting from hot_spots if available
        if hot_spots: # hot_spots is List[HotSpotData]
            valid_hot_spots = [hs for hs in hot_spots if hs.get('weight', 0) > 0] # Filter out zero or negative weight
            if valid_hot_spots:
                total_weight = sum(hs['weight'] for hs in valid_hot_spots)
                try:
                    chosen_hot_spot = random.choices(valid_hot_spots, weights=[hs['weight'] for hs in valid_hot_spots], k=1)[0]
                    base_lat = chosen_hot_spot['lat']
                    base_lng = chosen_hot_spot['lng']
                    accuracy = chosen_hot_spot['accuracy'] # Use hotspot's accuracy
                    from_source = chosen_hot_spot['name']
                    self.logger.log(f"基于热点 '{from_source}' (权重 {chosen_hot_spot['weight']}) 选择基础坐标。", LogLevel.DEBUG)
                except Exception as e:
                    self.logger.log(f"选择热点时出错 (学校ID: {school['id']}): {e}，将使用范围中心。", LogLevel.WARNING)
                    chosen_hot_spot = None # Fallback to range center

        # Step B: Use range center if no valid hotspot was chosen
        if chosen_hot_spot is None:
            min_lat, max_lat, min_lng, max_lng = range_data
            base_lat = (min_lat + max_lat) / 2
            base_lng = (min_lng + max_lng) / 2
            # accuracy remains default
            from_source = "校区中心区域"
            self.logger.log(f"无有效热点或选择失败，使用Range中心点作为基础坐标。", LogLevel.DEBUG)

        # Step C: Apply random offset
        final_lat, final_lng = base_lat, base_lng # Start with base
        try:
            # Only apply offset if max distance is positive
            if AppConstants.MAX_RANDOM_OFFSET_METERS > 0:
                 final_lat, final_lng = self._add_random_offset(base_lat, base_lng, AppConstants.MAX_RANDOM_OFFSET_METERS)

                 # Step D: Check if offset point is within range (simple fallback)
                 min_lat, max_lat, min_lng, max_lng = range_data
                 if not (min_lat <= final_lat <= max_lat and min_lng <= final_lng <= max_lng):
                     self.logger.log(f"随机偏移坐标 ({final_lat:.6f}, {final_lng:.6f}) 超出范围，使用原始基础点。", LogLevel.DEBUG)
                     final_lat, final_lng = base_lat, base_lng # Revert if out of bounds
                 else:
                      self.logger.log(f"应用随机偏移 ({random.uniform(0, AppConstants.MAX_RANDOM_OFFSET_METERS):.1f}m 内)，最终坐标: ({final_lat:.6f}, {final_lng:.6f})", LogLevel.DEBUG)
            else:
                 self.logger.log("最大随机偏移距离设置为0，不应用偏移。", LogLevel.DEBUG)


        except Exception as e:
            self.logger.log(f"计算随机偏移时出错: {e}，将使用原始基础坐标。", LogLevel.ERROR)
            final_lat, final_lng = base_lat, base_lng # Fallback on error

        return {
            "lat": f"{final_lat:.6f}",       # Format as string with 6 decimals
            "lng": f"{final_lng:.6f}",       # Format as string with 6 decimals
            "accuracy": f"{accuracy:.1f}", # Format as string with 1 decimal
            "from_location_name": from_source
        }

    def _add_random_offset(self, lat_deg: float, lng_deg: float, max_offset_meters: float) -> Tuple[float, float]:
        """Applies a random offset to coordinates using a simplified spherical model."""
        if max_offset_meters <= 0:
            return lat_deg, lng_deg

        # Random distance and bearing
        distance_meters = random.uniform(0, max_offset_meters)
        bearing_rad = random.uniform(0, 2 * math.pi) # Angle in radians

        # Convert lat/lng to radians
        lat_rad = math.radians(lat_deg)
        lng_rad = math.radians(lng_deg)

        # Calculate angular distance
        angular_distance = distance_meters / AppConstants.EARTH_RADIUS_METERS

        # Calculate new latitude
        new_lat_rad = math.asin(math.sin(lat_rad) * math.cos(angular_distance) +
                                math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad))

        # Calculate new longitude
        new_lng_rad = lng_rad + math.atan2(math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
                                           math.cos(angular_distance) - math.sin(lat_rad) * math.sin(new_lat_rad))

        # Convert back to degrees
        new_lat_deg = math.degrees(new_lat_rad)
        new_lng_deg = math.degrees(new_lng_rad)

        # Normalize longitude to [-180, 180]
        new_lng_deg = (new_lng_deg + 540) % 360 - 180
        # Clamp latitude to [-90, 90] (though formula should handle it)
        new_lat_deg = max(-90.0, min(90.0, new_lat_deg))

        return new_lat_deg, new_lng_deg

    @staticmethod
    def get_map_link(lat: float, lng: float, name: str = "推荐签到点") -> str:
        """Generates an Amap (Gaode) map link."""
        try:
             encoded_name = requests.utils.quote(name)
             # Ensure lat/lng are formatted correctly
             return f"https://uri.amap.com/marker?position={lng:.6f},{lat:.6f}&name={encoded_name}"
        except Exception:
             # Fallback or log error if quoting fails
             return f"https://uri.amap.com/marker?position={lng},{lat}" # Raw link if quoting fails

