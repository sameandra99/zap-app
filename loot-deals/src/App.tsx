import { useState } from "react";
import { Button } from "@/components/ui/button";

const deals = [
  {
    id: 1,
    brand: "Myntra",
    brandColor: "#FF3F6C",
    category: "Fashion",
    title: "Roadster Oversized Tee",
    description: "100% cotton, 12 colours",
    image: "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=400&h=400&fit=crop",
    originalPrice: 1299,
    dealPrice: 299,
    discount: 77,
    timeLeft: "2h 14m",
    dealScore: 94,
    badge: "HOT",
    badgeColor: "#FF3F6C",
    soldCount: "2.4k bought",
    tag: "Aaj Ka Loot",
  },
  {
    id: 2,
    brand: "Nykaa",
    brandColor: "#FC2779",
    category: "Beauty",
    title: "Maybelline Fit Me Foundation",
    description: "30ml, SPF 18, matte finish",
    image: "https://images.unsplash.com/photo-1631730486572-226d1f595058?w=400&h=400&fit=crop",
    originalPrice: 799,
    dealPrice: 319,
    discount: 60,
    timeLeft: "45m",
    dealScore: 88,
    badge: "ENDING SOON",
    badgeColor: "#F59E0B",
    soldCount: "890 bought",
    tag: "Loot Price",
  },
  {
    id: 3,
    brand: "Amazon",
    brandColor: "#FF9900",
    category: "Home",
    title: "Prestige Induction Cooktop",
    description: "2000W, 8 preset menus",
    image: "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=400&h=400&fit=crop",
    originalPrice: 3499,
    dealPrice: 1299,
    discount: 63,
    timeLeft: "5h 30m",
    dealScore: 91,
    badge: "HOT",
    badgeColor: "#FF3F6C",
    soldCount: "1.1k bought",
    tag: "Loot Price",
  },
  {
    id: 4,
    brand: "Flipkart",
    brandColor: "#2874F0",
    category: "Electronics",
    title: "boAt Airdopes 141",
    description: "42hr battery, ENx™ tech",
    image: "https://images.unsplash.com/photo-1572536147248-ac59a8abfa4b?w=400&h=400&fit=crop",
    originalPrice: 2990,
    dealPrice: 899,
    discount: 70,
    timeLeft: "1h 05m",
    dealScore: 97,
    badge: "ENDING SOON",
    badgeColor: "#F59E0B",
    soldCount: "5.2k bought",
    tag: "Aaj Ka Loot",
  },
];

function DealScoreRing({ score }: { score: number }) {
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 90 ? "#10B981" : score >= 75 ? "#F59E0B" : "#EF4444";

  return (
    <div className="relative flex items-center justify-center" style={{ width: 48, height: 48 }}>
      <svg width="48" height="48" style={{ transform: "rotate(-90deg)" }}>
        <circle cx="24" cy="24" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
        <circle
          cx="24" cy="24" r={radius} fill="none"
          stroke={color} strokeWidth="3"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute flex flex-col items-center justify-center">
        <span style={{ fontSize: 11, fontWeight: 700, color, lineHeight: 1 }}>{score}</span>
        <span style={{ fontSize: 7, color: "rgba(255,255,255,0.4)", lineHeight: 1, marginTop: 1 }}>AI</span>
      </div>
    </div>
  );
}

function DealCard({ deal, saved, onSave }: { deal: typeof deals[0]; saved: boolean; onSave: () => void }) {
  return (
    <div style={{
      background: "linear-gradient(145deg, #13131A 0%, #0F0F18 100%)",
      border: "1px solid rgba(255,255,255,0.07)",
      borderRadius: 20,
      overflow: "hidden",
      position: "relative",
      marginBottom: 12,
    }}>
      {/* Image section */}
      <div style={{ position: "relative", height: 200, overflow: "hidden" }}>
        <img src={deal.image} alt={deal.title}
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
        <div style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(to bottom, rgba(0,0,0,0.1) 0%, rgba(10,10,15,0.85) 100%)"
        }} />

        {/* Badge */}
        <div style={{ position: "absolute", top: 12, left: 12 }}>
          <span style={{
            background: deal.badgeColor, color: "#fff",
            fontSize: 10, fontWeight: 800, letterSpacing: "0.08em",
            padding: "3px 8px", borderRadius: 6, textTransform: "uppercase" as const,
          }}>{deal.badge}</span>
        </div>

        {/* Discount */}
        <div style={{
          position: "absolute", top: 12, right: 12,
          background: "rgba(124,58,237,0.9)", backdropFilter: "blur(8px)",
          borderRadius: 12, padding: "4px 10px",
          border: "1px solid rgba(139,92,246,0.4)",
        }}>
          <span style={{ color: "#fff", fontSize: 15, fontWeight: 800 }}>-{deal.discount}%</span>
        </div>

        {/* Brand */}
        <div style={{ position: "absolute", bottom: 12, left: 12 }}>
          <span style={{
            color: deal.brandColor, fontSize: 11, fontWeight: 700,
            letterSpacing: "0.06em", textTransform: "uppercase" as const,
            background: "rgba(0,0,0,0.4)", backdropFilter: "blur(8px)",
            padding: "3px 8px", borderRadius: 6,
          }}>{deal.brand}</span>
        </div>

        {/* Actions */}
        <div style={{ position: "absolute", bottom: 8, right: 12, display: "flex", gap: 8 }}>
          <button onClick={onSave} style={{
            background: saved ? "rgba(124,58,237,0.8)" : "rgba(0,0,0,0.4)",
            backdropFilter: "blur(8px)",
            border: saved ? "1px solid rgba(139,92,246,0.6)" : "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8, width: 32, height: 32,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", color: "#fff", fontSize: 14,
          }}>{saved ? "♥" : "♡"}</button>
          <button style={{
            background: "rgba(0,0,0,0.4)", backdropFilter: "blur(8px)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8, width: 32, height: 32,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", color: "#fff", fontSize: 13,
          }}>↑</button>
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: "14px 16px 16px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
          <div style={{ flex: 1 }}>
            <span style={{
              fontSize: 10, fontWeight: 700, color: "#7C3AED",
              letterSpacing: "0.05em", textTransform: "uppercase" as const,
              display: "block", marginBottom: 4,
            }}>{deal.tag} · {deal.category}</span>
            <h3 style={{ color: "#fff", fontSize: 16, fontWeight: 700, lineHeight: 1.3, margin: 0, marginBottom: 3 }}>
              {deal.title}
            </h3>
            <p style={{ color: "rgba(255,255,255,0.4)", fontSize: 12, margin: 0 }}>{deal.description}</p>
          </div>
          <DealScoreRing score={deal.dealScore} />
        </div>

        {/* Price */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12, marginBottom: 12 }}>
          <span style={{ color: "#fff", fontSize: 22, fontWeight: 800 }}>
            ₹{deal.dealPrice.toLocaleString("en-IN")}
          </span>
          <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 14, textDecoration: "line-through" }}>
            ₹{deal.originalPrice.toLocaleString("en-IN")}
          </span>
          <span style={{
            marginLeft: "auto", color: "rgba(255,255,255,0.35)", fontSize: 11,
            display: "flex", alignItems: "center", gap: 4,
          }}>
            <span style={{ color: "#EF4444", fontSize: 10 }}>⏱</span>
            {deal.timeLeft} left
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: "rgba(255,255,255,0.25)", fontSize: 11 }}>🔥 {deal.soldCount}</span>
          <Button style={{
            marginLeft: "auto",
            background: "linear-gradient(135deg, #7C3AED 0%, #6D28D9 100%)",
            border: "none", borderRadius: 10, color: "#fff",
            fontSize: 13, fontWeight: 700, padding: "8px 20px",
            height: "auto", letterSpacing: "0.02em",
            boxShadow: "0 4px 15px rgba(124,58,237,0.35)",
          }}>Buy Now →</Button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("home");
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const [activeFilter, setActiveFilter] = useState("All");

  const filters = ["All", "Fashion", "Beauty", "Home", "Electronics"];
  const navItems = [
    { id: "home", icon: "⚡", label: "Deals" },
    { id: "categories", icon: "◈", label: "Browse" },
    { id: "saved", icon: "♥", label: "Saved" },
    { id: "alerts", icon: "◎", label: "Alerts" },
  ];

  const toggleSave = (id: number) => {
    setSaved(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const filteredDeals = activeFilter === "All"
    ? deals
    : deals.filter(d => d.category === activeFilter);

  return (
    <div style={{
      background: "#0A0A0F", minHeight: "100vh",
      maxWidth: 390, margin: "0 auto",
      fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
      paddingBottom: 80,
    }}>
      {/* Status bar */}
      <div style={{ height: 44, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px" }}>
        <span style={{ color: "rgba(255,255,255,0.6)", fontSize: 13, fontWeight: 600 }}>9:41</span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }}>●●● WiFi 100%</span>
        </div>
      </div>

      {/* Top bar */}
      <div style={{ display: "flex", alignItems: "center", padding: "0 20px 12px", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 32, height: 32,
            background: "linear-gradient(135deg, #7C3AED, #5B21B6)",
            borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16,
          }}>⚡</div>
          <span style={{ color: "#fff", fontSize: 20, fontWeight: 900, letterSpacing: "-0.04em" }}>
            LOOT<span style={{ color: "#7C3AED" }}>.</span>
          </span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {["🔍", "🔔"].map((icon, i) => (
            <button key={i} style={{
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: 10, width: 36, height: 36,
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", fontSize: 15,
            }}>{icon}</button>
          ))}
        </div>
      </div>

      {/* Hero strip */}
      <div style={{
        margin: "0 20px 16px",
        background: "linear-gradient(135deg, rgba(124,58,237,0.15) 0%, rgba(91,33,182,0.08) 100%)",
        border: "1px solid rgba(124,58,237,0.2)",
        borderRadius: 16, padding: "12px 16px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div>
          <p style={{ color: "rgba(255,255,255,0.45)", fontSize: 11, margin: 0, marginBottom: 2 }}>Today's haul</p>
          <p style={{ color: "#fff", fontSize: 15, fontWeight: 700, margin: 0 }}>47 loot deals live ⚡</p>
        </div>
        <div style={{ textAlign: "right" }}>
          <p style={{ color: "rgba(255,255,255,0.45)", fontSize: 11, margin: 0, marginBottom: 2 }}>Avg saving</p>
          <p style={{ color: "#10B981", fontSize: 15, fontWeight: 700, margin: 0 }}>₹1,240</p>
        </div>
      </div>

      {/* Filter pills */}
      <div style={{ display: "flex", gap: 8, padding: "0 20px 16px", overflowX: "auto", scrollbarWidth: "none" }}>
        {filters.map(f => (
          <button key={f} onClick={() => setActiveFilter(f)} style={{
            flexShrink: 0,
            background: activeFilter === f ? "linear-gradient(135deg, #7C3AED, #6D28D9)" : "rgba(255,255,255,0.05)",
            border: activeFilter === f ? "1px solid rgba(139,92,246,0.4)" : "1px solid rgba(255,255,255,0.07)",
            borderRadius: 20, padding: "6px 14px",
            color: activeFilter === f ? "#fff" : "rgba(255,255,255,0.45)",
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            boxShadow: activeFilter === f ? "0 4px 12px rgba(124,58,237,0.3)" : "none",
          }}>{f}</button>
        ))}
      </div>

      {/* Section label */}
      <div style={{ padding: "0 20px 12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ color: "rgba(255,255,255,0.5)", fontSize: 12, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" as const }}>
          {filteredDeals.length} deals · AI curated
        </span>
        <span style={{ color: "#7C3AED", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Sort ↕</span>
      </div>

      {/* Cards */}
      <div style={{ padding: "0 20px" }}>
        {filteredDeals.length > 0 ? filteredDeals.map(deal => (
          <DealCard key={deal.id} deal={deal} saved={saved.has(deal.id)} onSave={() => toggleSave(deal.id)} />
        )) : (
          <div style={{ textAlign: "center", padding: "60px 0", color: "rgba(255,255,255,0.3)" }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>◈</div>
            <p style={{ fontSize: 14 }}>No deals in this category right now</p>
          </div>
        )}
      </div>

      {/* Bottom nav */}
      <div style={{
        position: "fixed", bottom: 0, left: "50%", transform: "translateX(-50%)",
        width: 390, maxWidth: "100%",
        background: "rgba(10,10,15,0.95)", backdropFilter: "blur(20px)",
        borderTop: "1px solid rgba(255,255,255,0.07)",
        display: "flex", padding: "10px 0 24px", zIndex: 50,
      }}>
        {navItems.map(item => (
          <button key={item.id} onClick={() => setActiveTab(item.id)} style={{
            flex: 1, display: "flex", flexDirection: "column",
            alignItems: "center", gap: 3,
            background: "none", border: "none", cursor: "pointer", padding: "4px 0",
          }}>
            <span style={{ fontSize: 18, opacity: activeTab === item.id ? 1 : 0.3 }}>{item.icon}</span>
            <span style={{
              fontSize: 10, fontWeight: 600,
              color: activeTab === item.id ? "#7C3AED" : "rgba(255,255,255,0.3)",
              letterSpacing: "0.04em",
            }}>{item.label}</span>
            {activeTab === item.id && (
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#7C3AED", boxShadow: "0 0 6px #7C3AED" }} />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
