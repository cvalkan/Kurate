import { Link, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Trophy, Shield } from "lucide-react";

export default function Navbar() {
  const location = useLocation();

  return (
    <nav className="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl">
        <div className="flex h-14 items-center justify-between">
          <Link
            to="/"
            className="flex items-center gap-2.5 hover:opacity-80 transition-opacity"
            data-testid="navbar-logo"
          >
            <Trophy className="h-5 w-5 text-accent" />
            <span className="font-heading font-semibold text-lg tracking-tight">
              Paper<span className="text-accent">Sumo</span>
            </span>
            <span className="hidden sm:inline text-xs text-muted-foreground font-mono border border-border rounded px-1.5 py-0.5">
              ROBOTICS
            </span>
          </Link>

          <div className="flex items-center gap-1">
            <Button
              variant={location.pathname === "/" ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-leaderboard"
            >
              <Link to="/" className="flex items-center gap-2">
                <Trophy className="h-4 w-4" />
                <span className="hidden sm:inline">Leaderboard</span>
              </Link>
            </Button>

            <Button
              variant={location.pathname.startsWith("/admin") ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-admin"
            >
              <Link to="/admin" className="flex items-center gap-2">
                <Shield className="h-4 w-4" />
                <span className="hidden sm:inline">Admin</span>
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </nav>
  );
}
