import { Link, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { FlaskConical, History, Home, Search } from "lucide-react";

export default function Navbar() {
  const location = useLocation();
  
  const isActive = (path) => {
    if (path === "/") return location.pathname === "/";
    return location.pathname.startsWith(path);
  };

  return (
    <nav className="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container-main">
        <div className="flex h-16 items-center justify-between">
          <Link 
            to="/" 
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            data-testid="navbar-logo"
          >
            <FlaskConical className="h-6 w-6 text-accent" />
            <span className="font-heading font-semibold text-lg">
              Paper<span className="text-accent">Sumo</span>
            </span>
          </Link>

          <div className="flex items-center gap-1">
            <Button
              variant={isActive("/") ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-home"
            >
              <Link to="/" className="flex items-center gap-2">
                <Home className="h-4 w-4" />
                <span className="hidden sm:inline">Home</span>
              </Link>
            </Button>

            <Button
              variant={isActive("/search") ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-search"
            >
              <Link to="/search" className="flex items-center gap-2">
                <Search className="h-4 w-4" />
                <span className="hidden sm:inline">Search</span>
              </Link>
            </Button>
            
            <Button
              variant={isActive("/history") ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-history"
            >
              <Link to="/history" className="flex items-center gap-2">
                <History className="h-4 w-4" />
                <span className="hidden sm:inline">History</span>
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </nav>
  );
}
