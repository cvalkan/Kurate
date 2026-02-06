import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  FileSearch,
  MessageSquare,
  ChevronDown,
  ScrollText,
  Target,
  TrendingUp,
  Quote,
  Bot
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Helper to get short model display name
const getModelDisplayName = (llmModel) => {
  if (!llmModel) return "GPT-5.2";
  const model = llmModel.model || llmModel;
  const modelNames = {
    "gpt-5.2": "GPT-5.2",
    "gpt-4o": "GPT-4o",
    "gpt-4o-mini": "GPT-4o Mini",
    "claude-opus-4-6-20250501": "Opus 4.6",
    "claude-opus-4-5-20251101": "Opus 4.5",
    "claude-sonnet-4-5-20250514": "Sonnet 4.5",
    "claude-haiku-4-5-20250514": "Haiku 4.5",
    "gemini-3-flash-preview": "Gemini 3",
    "gemini-2.0-flash": "Gemini 2.0",
    "gemini-1.5-pro": "Gemini 1.5"
  };
  return modelNames[model] || model;
};

export default function ResultsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [tournament, setTournament] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [matches, setMatches] = useState([]);
  const [papers, setPapers] = useState([]);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const [matchesLoaded, setMatchesLoaded] = useState(false);

  useEffect(() => {
    fetchTournament();
  }, [id]);

  const fetchTournament = async () => {
    try {
      const response = await axios.get(`${API}/tournaments/${id}/results`);
      const data = response.data.tournament;
      
      setTournament(data);
      setPapers(data.papers || []);
    } catch (err) {
      if (err.response?.status === 400) {
        // Tournament not completed, redirect to tournament page
        navigate(`/tournament/${id}`);
        return;
      }
      setError(err.response?.data?.detail || "Failed to load results");
    } finally {
      setLoading(false);
    }
  };

  const fetchMatches = async () => {
    if (matchesLoaded || matchesLoading) return;
    
    setMatchesLoading(true);
    try {
      const response = await axios.get(`${API}/tournaments/${id}/matches?limit=500`);
      setMatches(response.data.matches || []);
      setPapers(response.data.papers || papers);
      setMatchesLoaded(true);
    } catch (err) {
      toast.error("Failed to load comparison logs");
    } finally {
      setMatchesLoading(false);
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

  const getPaperTitle = (paperId) => {
    const paper = papers?.find(p => p.id === paperId);
    return paper?.title || "Unknown paper";
  };

  const getPaperLink = (paperId) => {
    const paper = papers?.find(p => p.id === paperId);
    return paper?.link || "#";
  };

  const getPaperCitations = (paperId) => {
    const paper = papers?.find(p => p.id === paperId);
    return paper?.citation_count;
  };

  // Create paper lookup map for rankings
  const paperLookup = papers.reduce((acc, p) => {
    acc[p.id] = p;
    return acc;
  }, {});

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
          {tournament.category_name}
          {tournament.category !== 'custom' && ` (${tournament.category})`}
        </p>
        
        {/* Stats */}
        <div className="flex flex-wrap gap-6 mt-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            <span>{tournament.num_papers} papers</span>
          </div>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            <span>
              {tournament.successful_matches || tournament.total_matches} comparisons
              {tournament.failed_matches > 0 && (
                <span className="text-amber-600 ml-1">({tournament.failed_matches} failed)</span>
              )}
            </span>
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
          {tournament.ranking_mode === 'ucb' && (
            <Badge variant="outline" className="border-purple-300 text-purple-700 bg-purple-50">
              <Target className="h-3 w-3 mr-1" />
              UCB Mode
            </Badge>
          )}
          <Badge variant="outline" className="border-blue-300 text-blue-700 bg-blue-50" data-testid="model-badge">
            <Bot className="h-3 w-3 mr-1" />
            {getModelDisplayName(tournament.llm_model)}
          </Badge>
        </div>
      </div>

      {/* Top 3 Podium */}
      <div className="mb-12">
        <h2 className="text-lg font-heading font-semibold mb-6 flex items-center gap-2">
          <Medal className="h-5 w-5 text-accent" />
          Top Ranked Papers
        </h2>
        
        {/* Horizontal scroll on mobile */}
        <div className="flex md:grid md:grid-cols-3 gap-4 md:gap-6 overflow-x-auto pb-4 md:pb-0 snap-x snap-mandatory md:snap-none -mx-4 px-4 md:mx-0 md:px-0">
          {topThree.map((item, index) => {
            return (
              <Card 
                key={item.paper_id}
                className={`relative overflow-hidden border-2 ${getRankStyle(item.rank)} animate-slide-up flex-shrink-0 w-[85vw] md:w-auto snap-center`}
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
                      <div className="flex items-center gap-2 mt-2">
                        <p className="text-xs text-muted-foreground flex items-center gap-1">
                          <Users className="h-3 w-3" />
                          {item.authors?.slice(0, 2).join(", ")}
                          {item.authors?.length > 2 && " et al."}
                        </p>
                        {paperLookup[item.paper_id]?.citation_count !== null && 
                         paperLookup[item.paper_id]?.citation_count !== undefined && (
                          <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 bg-amber-50">
                            <Quote className="h-2.5 w-2.5 mr-1" />
                            {paperLookup[item.paper_id].citation_count} citations
                          </Badge>
                        )}
                      </div>
                    </div>
                    
                    <Separator />
                    
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-muted-foreground">Bradley-Terry Score</p>
                        <p className="text-xl font-mono font-bold text-accent" data-testid={`score-${index + 1}`}>
                          {item.score.toFixed(4)}
                        </p>
                        {/* Confidence Band for Top 3 */}
                        {item.confidence && (
                          <p className="text-xs font-mono text-muted-foreground mt-1" data-testid={`top-confidence-${index + 1}`}>
                            Win rate: <span className="text-green-600">{(item.confidence.win_rate * 100).toFixed(0)}%</span>
                            <span className="mx-1">±</span>
                            <span>{(item.confidence.margin_of_error * 100).toFixed(0)}%</span>
                          </p>
                        )}
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

      {/* Tabs for Rankings and Logs */}
      <Tabs defaultValue="rankings" className="w-full" onValueChange={(value) => {
        if (value === 'logs') {
          fetchMatches();
        }
      }}>
        <TabsList className="grid w-full max-w-md grid-cols-2 mb-6">
          <TabsTrigger value="rankings" className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            Rankings
          </TabsTrigger>
          <TabsTrigger value="logs" className="flex items-center gap-2" data-testid="view-logs-tab">
            <ScrollText className="h-4 w-4" />
            Comparison Logs
          </TabsTrigger>
        </TabsList>

        {/* Rankings Tab */}
        <TabsContent value="rankings">
          <Card data-testid="full-rankings-card">
            <CardHeader>
              <CardTitle className="text-lg">Complete Rankings</CardTitle>
              <CardDescription>
                All papers ranked by Bradley-Terry score
                {tournament.ranking_mode === 'ucb' && ' with confidence intervals'}
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
                        <div className="flex items-center gap-2 mt-0.5">
                          <p className="text-xs text-muted-foreground truncate">
                            {item.authors?.slice(0, 3).join(", ")}
                          </p>
                          {paperLookup[item.paper_id]?.citation_count !== null && 
                           paperLookup[item.paper_id]?.citation_count !== undefined && (
                            <Badge variant="outline" className="text-[10px] py-0 border-amber-300 text-amber-700 bg-amber-50">
                              <Quote className="h-2 w-2 mr-0.5" />
                              {paperLookup[item.paper_id].citation_count}
                            </Badge>
                          )}
                        </div>
                      </div>
                      
                      <div className="flex-shrink-0 text-right min-w-[120px]">
                        <p className="font-mono font-semibold text-accent">
                          {item.score.toFixed(4)}
                        </p>
                        {/* Confidence Band */}
                        {item.confidence && (
                          <div className="text-[10px] text-muted-foreground font-mono" data-testid={`confidence-${index}`}>
                            <span className="text-green-600">{(item.confidence.win_rate * 100).toFixed(0)}%</span>
                            <span className="mx-1">±</span>
                            <span>{(item.confidence.margin_of_error * 100).toFixed(0)}%</span>
                            <span className="text-muted-foreground/60 ml-1">
                              ({item.confidence.comparisons} cmp)
                            </span>
                          </div>
                        )}
                        {!item.confidence && (
                          <p className="text-xs font-mono text-muted-foreground">
                            {item.arxiv_id}
                          </p>
                        )}
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
        </TabsContent>

        {/* Logs Tab */}
        <TabsContent value="logs">
          <Card data-testid="comparison-logs-card">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <ScrollText className="h-5 w-5" />
                All Comparison Logs
              </CardTitle>
              <CardDescription>
                {matchesLoaded ? `${matches.length} pairwise comparisons with AI reasoning` : 'Click to load comparison logs'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {matchesLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-accent" />
                  <span className="ml-2 text-muted-foreground">Loading logs...</span>
                </div>
              ) : !matchesLoaded ? (
                <div className="flex items-center justify-center py-12">
                  <span className="text-muted-foreground">Logs will load when this tab is selected</span>
                </div>
              ) : (
              <ScrollArea className="h-[500px] pr-4">
                <div className="space-y-3">
                  {matches.map((match, index) => {
                    const winnerTitle = getPaperTitle(match.winner_id);
                    const loserTitle = getPaperTitle(
                      match.winner_id === match.paper1_id ? match.paper2_id : match.paper1_id
                    );
                    const winnerLink = getPaperLink(match.winner_id);
                    
                    return (
                      <Collapsible key={match.id}>
                        <div 
                          className="rounded-lg bg-secondary/50 text-xs overflow-hidden"
                          data-testid={`log-entry-${index}`}
                        >
                          <CollapsibleTrigger className="w-full p-3 hover:bg-secondary/80 transition-colors">
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex-1 min-w-0 text-left">
                                <div className="flex items-center gap-2">
                                  <span className="text-muted-foreground font-mono">#{index + 1}</span>
                                  <Trophy className="h-3 w-3 text-amber-500 flex-shrink-0" />
                                  <span className="font-medium text-foreground truncate">
                                    {winnerTitle.slice(0, 40)}...
                                  </span>
                                </div>
                                <div className="flex items-center gap-2 mt-1 text-muted-foreground pl-10">
                                  <span className="text-[10px]">beat</span>
                                  <span className="truncate">
                                    {loserTitle.slice(0, 40)}...
                                  </span>
                                </div>
                              </div>
                              <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                            </div>
                          </CollapsibleTrigger>
                          
                          <CollapsibleContent>
                            <div className="px-3 pb-3 pt-1 border-t border-border/50 space-y-3">
                              <div className="flex items-start gap-2">
                                <MessageSquare className="h-3 w-3 text-accent mt-0.5 flex-shrink-0" />
                                <p className="text-muted-foreground leading-relaxed">
                                  {match.reasoning || "No reasoning provided"}
                                </p>
                              </div>
                              <div className="flex gap-2">
                                <Button size="sm" variant="outline" asChild className="h-7 text-xs">
                                  <a href={winnerLink} target="_blank" rel="noopener noreferrer">
                                    View Winner
                                    <ExternalLink className="h-3 w-3 ml-1" />
                                  </a>
                                </Button>
                              </div>
                            </div>
                          </CollapsibleContent>
                        </div>
                      </Collapsible>
                    );
                  })}
                </div>
              </ScrollArea>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

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
