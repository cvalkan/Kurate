import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { 
  Trophy, 
  Loader2, 
  XCircle, 
  ArrowLeft,
  ExternalLink,
  Medal,
  BarChart3,
  Users,
  Calendar,
  FileText,
  FileSearch
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function ResultsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [tournament, setTournament] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchTournament();
  }, [id]);

  const fetchTournament = async () => {
    try {
      const response = await axios.get(`${API}/tournaments/${id}`);
      const data = response.data.tournament;
      
      if (data.status !== 'completed') {
        navigate(`/tournament/${id}`);
        return;
      }
      
      setTournament(data);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load results");
    } finally {
      setLoading(false);
    }
  };

  const getRankStyle = (rank) => {
    switch (rank) {
      case 1:
        return "bg-gradient-to-r from-amber-50 to-amber-100 border-amber-300";
      case 2:
        return "bg-gradient-to-r from-slate-50 to-slate-100 border-slate-300";
      case 3:
        return "bg-gradient-to-r from-orange-50 to-orange-100 border-orange-300";
      default:
        return "bg-card border-border";
    }
  };

  const getRankBadge = (rank) => {
    switch (rank) {
      case 1:
        return <span className="rank-badge rank-1">1</span>;
      case 2:
        return <span className="rank-badge rank-2">2</span>;
      case 3:
        return <span className="rank-badge rank-3">3</span>;
      default:
        return <span className="rank-badge rank-default">{rank}</span>;
    }
  };

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center space-y-4">
          <Loader2 className="h-12 w-12 animate-spin text-accent mx-auto" />
          <p className="text-muted-foreground">Loading results...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <Card className="max-w-md">
          <CardContent className="pt-6 text-center space-y-4">
            <XCircle className="h-12 w-12 text-destructive mx-auto" />
            <p className="text-destructive">{error}</p>
            <Button onClick={() => navigate("/")} variant="outline">
              Go Home
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const topThree = tournament.rankings?.slice(0, 3) || [];
  const remaining = tournament.rankings?.slice(3) || [];

  return (
    <div className="container-main py-8" data-testid="results-page">
      {/* Header */}
      <div className="mb-8">
        <Button 
          variant="ghost" 
          size="sm" 
          onClick={() => navigate("/history")}
          className="mb-4"
          data-testid="back-btn"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to History
        </Button>
        
        <div className="flex flex-wrap items-center gap-3 mb-2">
          <Trophy className="h-8 w-8 text-amber-500" />
          <h1 className="text-heading-2" data-testid="results-title">
            Tournament Results
          </h1>
        </div>
        <p className="text-muted-foreground">
          {tournament.category_name} ({tournament.category})
        </p>
        
        {/* Stats */}
        <div className="flex flex-wrap gap-6 mt-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            <span>{tournament.num_papers} papers</span>
          </div>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            <span>{tournament.total_matches} comparisons</span>
          </div>
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4" />
            <span>{new Date(tournament.completed_at).toLocaleDateString()}</span>
          </div>
          {tournament.deep_analysis && (
            <Badge variant="outline" className="border-green-300 text-green-700 bg-green-50">
              <FileSearch className="h-3 w-3 mr-1" />
              Deep Analysis
            </Badge>
          )}
        </div>
      </div>

      {/* Top 3 Podium */}
      <div className="mb-12">
        <h2 className="text-lg font-heading font-semibold mb-6 flex items-center gap-2">
          <Medal className="h-5 w-5 text-accent" />
          Top Ranked Papers
        </h2>
        
        <div className="grid md:grid-cols-3 gap-6">
          {topThree.map((item, index) => {
            const paper = tournament.papers?.find(p => p.id === item.paper_id);
            return (
              <Card 
                key={item.paper_id}
                className={`relative overflow-hidden border-2 ${getRankStyle(item.rank)} animate-slide-up`}
                style={{ animationDelay: `${index * 0.1}s` }}
                data-testid={`top-paper-${index + 1}`}
              >
                <CardContent className="pt-6">
                  <div className="absolute top-4 right-4">
                    {getRankBadge(item.rank)}
                  </div>
                  
                  <div className="space-y-4">
                    <div>
                      <h3 className="font-heading font-semibold text-base leading-tight line-clamp-3 pr-10">
                        {item.title}
                      </h3>
                      <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1">
                        <Users className="h-3 w-3" />
                        {item.authors?.slice(0, 2).join(", ")}
                        {item.authors?.length > 2 && " et al."}
                      </p>
                    </div>
                    
                    <Separator />
                    
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-muted-foreground">Bradley-Terry Score</p>
                        <p className="text-xl font-mono font-bold text-accent" data-testid={`score-${index + 1}`}>
                          {item.score.toFixed(4)}
                        </p>
                      </div>
                      <Button 
                        size="sm" 
                        variant="outline"
                        asChild
                      >
                        <a 
                          href={item.link} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          data-testid={`paper-link-${index + 1}`}
                        >
                          View
                          <ExternalLink className="h-3 w-3 ml-1" />
                        </a>
                      </Button>
                    </div>
                    
                    <p className="text-xs font-mono text-muted-foreground">
                      {item.arxiv_id}
                    </p>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Full Rankings Table */}
      <Card data-testid="full-rankings-card">
        <CardHeader>
          <CardTitle className="text-lg">Complete Rankings</CardTitle>
          <CardDescription>
            All papers ranked by Bradley-Terry score
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[400px]">
            <div className="space-y-2">
              {tournament.rankings?.map((item, index) => (
                <div 
                  key={item.paper_id}
                  className={`flex items-center gap-4 p-3 rounded-lg border ${
                    index < 3 ? getRankStyle(item.rank) : 'bg-card border-border'
                  } hover:border-accent/50 transition-colors`}
                  data-testid={`ranking-row-${index}`}
                >
                  <div className="flex-shrink-0">
                    {getRankBadge(item.rank)}
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <a 
                      href={item.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-sm hover:text-accent transition-colors line-clamp-1"
                    >
                      {item.title}
                    </a>
                    <p className="text-xs text-muted-foreground truncate">
                      {item.authors?.slice(0, 3).join(", ")}
                    </p>
                  </div>
                  
                  <div className="flex-shrink-0 text-right">
                    <p className="font-mono font-semibold text-accent">
                      {item.score.toFixed(4)}
                    </p>
                    <p className="text-xs font-mono text-muted-foreground">
                      {item.arxiv_id}
                    </p>
                  </div>
                  
                  <Button 
                    size="icon" 
                    variant="ghost"
                    asChild
                    className="flex-shrink-0"
                  >
                    <a 
                      href={item.link} 
                      target="_blank" 
                      rel="noopener noreferrer"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  </Button>
                </div>
              ))}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Actions */}
      <div className="mt-8 flex flex-wrap gap-4 justify-center">
        <Button variant="outline" onClick={() => navigate("/")}>
          <Trophy className="h-4 w-4 mr-2" />
          Start New Tournament
        </Button>
        <Button variant="outline" onClick={() => navigate("/history")}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          View All Tournaments
        </Button>
      </div>
    </div>
  );
}
