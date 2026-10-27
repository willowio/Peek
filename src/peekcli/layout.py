"""Terminal-cell geometry shared by every screen, pane and compact dialog."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    y: int
    x: int
    width: int
    height: int

    def inset(self, vertical=1, horizontal=1):
        return Rect(self.y + min(vertical, self.height), self.x + min(horizontal, self.width),
                    max(0, self.width - 2 * horizontal), max(0, self.height - 2 * vertical))

    def centered(self, width, height):
        width = max(0, min(width, self.width))
        height = max(0, min(height, self.height))
        return Rect(self.y + (self.height-height)//2, self.x + (self.width-width)//2, width, height)


@dataclass(frozen=True)
class Layout:
    header: Rect
    navigation: Rect
    heading: Rect
    filters: Rect
    body: Rect
    status: Rect
    footer: Rect
    wide: bool

    @classmethod
    def measure(cls, width, height):
        width, height = max(0, width), max(0, height)
        header_height = 6 if height >= 24 else 1
        nav = header_height + 1
        heading = nav + 2
        filters = heading + 1
        body = filters + (2 if height >= 24 else 1)
        usable_width = max(0, width-4)
        return cls(Rect(0,2,usable_width,header_height), Rect(nav,2,usable_width,1),
                   Rect(heading,2,usable_width,1), Rect(filters,2,usable_width,1),
                   Rect(body,2,usable_width,max(0,height-2-body)),
                   Rect(max(0,height-2),2,usable_width,1), Rect(max(0,height-1),2,usable_width,1),
                   width >= 100 and height >= 22)

    def panes(self):
        left = max(48, round(self.body.width*.56))
        left = min(left, self.body.width-38)
        listing = Rect(self.body.y,self.body.x,left,self.body.height)
        divider = Rect(self.body.y,self.body.x+left+1,1,self.body.height)
        details = Rect(self.body.y,self.body.x+left+4,max(0,self.body.width-left-4),self.body.height)
        return listing, divider, details
