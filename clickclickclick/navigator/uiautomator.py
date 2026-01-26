"""
UIAutomator Parser - Parses accessibility tree from Android devices.

Uses `adb shell uiautomator dump` to get XML representation of screen.
95% cheaper than screenshot + vision model approach.

Usage:
    parser = UIAutomatorParser()
    elements = parser.dump_and_parse()

    # Find element by text
    like_btn = parser.find_by_text("Like")

    # Find element by resource-id
    post_image = parser.find_by_id("com.instagram.android:id/media_container")

    # Find element by class
    buttons = parser.find_by_class("android.widget.Button")
"""
import subprocess
import xml.etree.ElementTree as ET
import re
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class UIElement:
    """Represents a UI element from accessibility tree."""

    # Core attributes
    resource_id: str = ""
    class_name: str = ""
    text: str = ""
    content_desc: str = ""

    # Bounds
    bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x1, y1, x2, y2

    # State
    clickable: bool = False
    enabled: bool = True
    focused: bool = False
    selected: bool = False
    scrollable: bool = False
    checkable: bool = False
    checked: bool = False

    # Hierarchy
    index: int = 0
    package: str = ""

    @property
    def center(self) -> Tuple[int, int]:
        """Get center point of element for tapping."""
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    @property
    def short_id(self) -> str:
        """Get short resource ID without package prefix."""
        if "/" in self.resource_id:
            return self.resource_id.split("/")[-1]
        return self.resource_id

    def matches_text(self, text: str, partial: bool = True) -> bool:
        """Check if element text matches."""
        if partial:
            return text.lower() in self.text.lower() or text.lower() in self.content_desc.lower()
        return self.text.lower() == text.lower() or self.content_desc.lower() == text.lower()

    def matches_id(self, resource_id: str) -> bool:
        """Check if element matches resource ID (partial match)."""
        return resource_id in self.resource_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "resource_id": self.short_id,
            "class": self.class_name.split(".")[-1],
            "text": self.text[:50] if self.text else "",
            "content_desc": self.content_desc[:50] if self.content_desc else "",
            "bounds": self.bounds,
            "center": self.center,
            "clickable": self.clickable,
        }

    def __repr__(self) -> str:
        text_preview = self.text[:20] if self.text else self.content_desc[:20] if self.content_desc else ""
        return f"UIElement({self.short_id or self.class_name.split('.')[-1]}, '{text_preview}', {self.center})"


class UIAutomatorParser:
    """
    Parses Android UI hierarchy using uiautomator.

    This is the core of the 90% scripted navigation approach.
    """

    def __init__(self, device_serial: Optional[str] = None):
        self.device_serial = device_serial
        self.elements: List[UIElement] = []
        self.raw_xml: str = ""
        self._screen_hash: str = ""

    def _adb_command(self, cmd: List[str]) -> str:
        """Execute ADB command with optional device serial."""
        full_cmd = ["adb"]
        if self.device_serial:
            full_cmd.extend(["-s", self.device_serial])
        full_cmd.extend(cmd)

        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"ADB error: {result.stderr}")
        return result.stdout

    def dump(self) -> str:
        """
        Dump UI hierarchy XML from device.
        Returns raw XML string.
        """
        # Dump to device
        self._adb_command(["shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"])

        # Pull XML content
        result = self._adb_command(["shell", "cat", "/sdcard/ui_dump.xml"])
        self.raw_xml = result

        # Calculate screen hash for obstacle detection
        self._screen_hash = hashlib.md5(result.encode()).hexdigest()[:12]

        return result

    def parse(self, xml_string: Optional[str] = None) -> List[UIElement]:
        """
        Parse XML string into UIElement list.
        If xml_string not provided, uses last dump.
        """
        xml_to_parse = xml_string or self.raw_xml
        if not xml_to_parse:
            logger.warning("No XML to parse, running dump first")
            self.dump()
            xml_to_parse = self.raw_xml

        self.elements = []

        try:
            root = ET.fromstring(xml_to_parse)
            self._parse_node(root)
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return []

        logger.debug(f"Parsed {len(self.elements)} elements")
        return self.elements

    def _parse_node(self, node: ET.Element):
        """Recursively parse XML node into UIElement."""

        # Parse bounds string "[x1,y1][x2,y2]"
        bounds_str = node.get("bounds", "[0,0][0,0]")
        bounds_match = re.findall(r'\[(\d+),(\d+)\]', bounds_str)
        if len(bounds_match) == 2:
            bounds = (
                int(bounds_match[0][0]),
                int(bounds_match[0][1]),
                int(bounds_match[1][0]),
                int(bounds_match[1][1])
            )
        else:
            bounds = (0, 0, 0, 0)

        element = UIElement(
            resource_id=node.get("resource-id", ""),
            class_name=node.get("class", ""),
            text=node.get("text", ""),
            content_desc=node.get("content-desc", ""),
            bounds=bounds,
            clickable=node.get("clickable", "false") == "true",
            enabled=node.get("enabled", "true") == "true",
            focused=node.get("focused", "false") == "true",
            selected=node.get("selected", "false") == "true",
            scrollable=node.get("scrollable", "false") == "true",
            checkable=node.get("checkable", "false") == "true",
            checked=node.get("checked", "false") == "true",
            index=int(node.get("index", "0")),
            package=node.get("package", ""),
        )

        # Only add elements with bounds (visible elements)
        if bounds != (0, 0, 0, 0):
            self.elements.append(element)

        # Recurse into children
        for child in node:
            self._parse_node(child)

    def dump_and_parse(self) -> List[UIElement]:
        """Convenience method: dump + parse in one call."""
        self.dump()
        return self.parse()

    @property
    def screen_hash(self) -> str:
        """Get hash of current screen for obstacle detection."""
        return self._screen_hash

    # =========================================================================
    # FINDER METHODS
    # =========================================================================

    def find_by_text(self, text: str, partial: bool = True, clickable_only: bool = False) -> Optional[UIElement]:
        """Find first element matching text."""
        for el in self.elements:
            if el.matches_text(text, partial):
                if clickable_only and not el.clickable:
                    continue
                return el
        return None

    def find_all_by_text(self, text: str, partial: bool = True) -> List[UIElement]:
        """Find all elements matching text."""
        return [el for el in self.elements if el.matches_text(text, partial)]

    def find_by_id(self, resource_id: str) -> Optional[UIElement]:
        """Find element by resource ID (partial match)."""
        for el in self.elements:
            if el.matches_id(resource_id):
                return el
        return None

    def find_all_by_id(self, resource_id: str) -> List[UIElement]:
        """Find all elements matching resource ID."""
        return [el for el in self.elements if el.matches_id(resource_id)]

    def find_by_class(self, class_name: str) -> List[UIElement]:
        """Find all elements of specific class."""
        return [el for el in self.elements if class_name in el.class_name]

    def find_clickable(self) -> List[UIElement]:
        """Find all clickable elements."""
        return [el for el in self.elements if el.clickable]

    def find_by_content_desc(self, desc: str, partial: bool = True) -> Optional[UIElement]:
        """Find element by content description (accessibility label)."""
        for el in self.elements:
            if partial:
                if desc.lower() in el.content_desc.lower():
                    return el
            else:
                if el.content_desc.lower() == desc.lower():
                    return el
        return None

    # =========================================================================
    # INSTAGRAM-SPECIFIC HELPERS
    # =========================================================================

    def is_instagram_open(self) -> bool:
        """Check if Instagram is the current app."""
        return any(el.package == "com.instagram.android" for el in self.elements)

    def find_instagram_element(self, element_type: str) -> Optional[UIElement]:
        """
        Find Instagram-specific UI elements.

        element_type: 'like', 'comment', 'share', 'save', 'follow', 'profile_tab', etc.
        """
        # Instagram resource ID patterns
        id_patterns = {
            "like": "row_feed_button_like",
            "comment": "row_feed_button_comment",
            "share": "row_feed_button_share",
            "save": "row_feed_button_save",
            "follow": "button",  # text-based: "Follow"
            "profile_tab": "profile_tab",
            "home_tab": "feed_tab",
            "search_tab": "search_tab",
            "reels_tab": "clips_tab",
            "post_image": "media_container",
            "username": "row_feed_photo_profile_name",
            "caption": "row_feed_comment_textview_layout",
        }

        pattern = id_patterns.get(element_type)
        if pattern:
            el = self.find_by_id(pattern)
            if el:
                return el

        # Fallback to content description
        desc_patterns = {
            "like": "Like",
            "comment": "Comment",
            "share": "Share",
            "save": "Save",
            "home_tab": "Home",
            "search_tab": "Search",
            "reels_tab": "Reels",
            "profile_tab": "Profile",
        }

        desc = desc_patterns.get(element_type)
        if desc:
            return self.find_by_content_desc(desc)

        return None

    def get_screen_summary(self) -> Dict[str, Any]:
        """Get summary of current screen for logging."""
        clickable = self.find_clickable()
        texts = [el.text for el in self.elements if el.text][:10]

        return {
            "screen_hash": self._screen_hash,
            "total_elements": len(self.elements),
            "clickable_elements": len(clickable),
            "is_instagram": self.is_instagram_open(),
            "visible_texts": texts,
        }
