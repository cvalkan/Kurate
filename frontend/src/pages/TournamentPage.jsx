import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { 
  Trophy, 
  Loader2, 
  CheckCircle2, 
  XCircle, 
  ArrowRight,
  FileText,
  Zap,
  Clock,
  FileSearch,
  Play,
  ChevronDown,
  MessageSquare,
  Target,
  Quote
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function TournamentPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [tournament, setTournament] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const eventSourceRef = useRef(null);
  const pollingRef = useRef(null);

  const fetchTournament = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/tournaments/${id}`);
      setTournament(response.data.tournament);
      setLoading(false);
      
      // If completed or failed, stop polling
      if (response.data.tournament.status === 'completed' || response.data.tournament.status === 'failed') {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load tournament");
      setLoading(false);
    }
  }, [id]);

  const handleStartTournament = async () => {
    setStarting(true);
    try {
      await axios.post(`${API}/tournaments/${id}/start`);
      toast.success("Tournament started!");
      fetchTournament();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to start tournament");
    } finally {
      setStarting(false);
    }
  };

  useEffect(() => {
    fetchTournament();
    
    // Poll for updates - only for running tournaments, longer interval
    pollingRef.current = setInterval(() => {
      // Only poll if tournament is running
      if (tournament?.status === 'running') {
        fetchTournament();
      }
    }, 4000);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [fetchTournament, tournament?.status]);

  const getStatusColor = (status) => {
    switch (status) {
      case 'pending': return 'bg-yellow-100 text-yellow-800';
      case 'running': return 'bg-blue-100 text-blue-800';
      case 'completed': return 'bg-green-100 text-green-800';
      case 'failed': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'pending': return Clock;
      case 'running': return Loader2;
      case 'completed': return CheckCircle2;
      case 'failed': return XCircle;
      default: return Clock;
    }
  };

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center space-y-4">
          <Loader2 className="h-12 w-12 animate-spin text-accent mx-auto" />
          <p className="text-muted-foreground">Loading tournament...</p>
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

  const StatusIcon = getStatusIcon(tournament.status);
  const completedMatches = tournament.matches?.filter(m => m.completed).length || 0;
  const totalMatches = tournament.total_matches || 0;

  return (
    <div className="container-main py-8" data-testid="tournament-page">
      {/* Header */}
      <div className="mb-8">
        <div className="flex flex-wrap items-center gap-3 mb-2">
          <h1 className="text-heading-3" data-testid="tournament-title">
            {tournament.category_name}
          </h1>
          <Badge className={getStatusColor(tournament.status)} data-testid="tournament-status">
            <StatusIcon className={`h-3 w-3 mr-1 ${tournament.status === 'running' ? 'animate-spin' : ''}`} />
            {tournament.status}
          </Badge>
        </div>
        <p className="text-muted-foreground font-mono text-sm flex items-center gap-2 flex-wrap">
          <span>{tournament.category}</span>
          <span>•</span>
          <span>{tournament.num_papers} papers</span>
          <span>•</span>
          <span>{tournament.parallel_agents} parallel agents</span>
          {tournament.deep_analysis && (
            <>
              <span>•</span>
              <Badge variant="outline" className="border-green-300 text-green-700 bg-green-50">
                <FileSearch className="h-3 w-3 mr-1" />
                Deep Analysis
              </Badge>
            </>
          )}
          {tournament.ranking_mode === 'ucb' && (
            <>
              <span>•</span>
              <Badge variant="outline" className="border-purple-300 text-purple-700 bg-purple-50">
                <Target className="h-3 w-3 mr-1" />
                UCB Mode
              </Badge>
            </>
          )}
        </p>
      </div>

      {/* Progress Section */}
      <Card className="mb-8" data-testid="progress-card">
        <CardContent className="pt-6">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="space-y-1">
                <p className="text-sm font-medium">Tournament Progress</p>
                <p className="text-xs text-muted-foreground">
                  {completedMatches} of {totalMatches} comparisons completed
                </p>
              </div>
              <span className="text-2xl font-mono font-bold text-accent" data-testid="progress-percentage">
                {tournament.progress || 0}%
              </span>
            </div>
            <Progress value={tournament.progress || 0} className="h-3" data-testid="progress-bar" />
            
            {tournament.current_log && (
              <p className="text-sm text-muted-foreground animate-pulse-subtle" data-testid="current-log">
                {tournament.current_log}
              </p>
            )}

            {/* Start/Retry button for pending or failed tournaments */}
            {(tournament.status === 'pending' || tournament.status === 'failed') && (
              <Button 
                onClick={handleStartTournament}
                disabled={starting}
                className="mt-4"
                data-testid="start-tournament-btn"
              >
                {starting ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Play className="h-4 w-4 mr-2" />
                )}
                {tournament.status === 'failed' ? 'Retry Tournament' : 'Start Tournament'}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Main Content Grid */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Papers List */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <FileText className="h-5 w-5" />
                Papers in Tournament
              </CardTitle>
              <CardDescription>
                {tournament.papers?.length || 0} papers being compared
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[500px] pr-4">
                <div className="space-y-3">
                  {tournament.papers?.map((paper, index) => (
                    <div 
                      key={paper.id}
                      className="p-4 rounded-lg border border-border hover:border-accent/50 transition-colors"
                      data-testid={`paper-card-${index}`}
                    >
                      <div className="flex items-start gap-3">
                        <span className="flex-shrink-0 w-6 h-6 rounded bg-secondary flex items-center justify-center text-xs font-mono">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <a 
                            href={paper.link} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="font-medium text-sm hover:text-accent transition-colors line-clamp-2"
                          >
                            {paper.title}
                          </a>
                          <div className="flex items-center gap-2 mt-1">
                            <p className="text-xs text-muted-foreground truncate">
                              {paper.authors?.slice(0, 3).join(", ")}
                              {paper.authors?.length > 3 && " et al."}
                            </p>
                            {paper.citation_count !== null && paper.citation_count !== undefined && (
                              <Badge variant="outline" className="text-[10px] py-0 border-amber-300 text-amber-700 bg-amber-50">
                                <Quote className="h-2 w-2 mr-0.5" />
                                {paper.citation_count}
                              </Badge>
                            )}
                          </div>
                          <p className="text-xs font-mono text-muted-foreground mt-1">
                            {paper.arxiv_id}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        {/* Matches Log */}
        <div>
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Zap className="h-5 w-5" />
                Comparison Log
              </CardTitle>
              <CardDescription>
                Recent match results
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[500px] pr-4">
                <div className="space-y-3">
                  {tournament.matches?.filter(m => m.completed).slice(-20).reverse().map((match, index) => {
                    const paper1 = tournament.papers?.find(p => p.id === match.paper1_id);
                    const paper2 = tournament.papers?.find(p => p.id === match.paper2_id);
                    const winner = tournament.papers?.find(p => p.id === match.winner_id);
                    const loser = match.winner_id === match.paper1_id ? paper2 : paper1;
                    
                    return (
                      <Collapsible key={match.id}>
                        <div 
                          className="rounded-lg bg-secondary/50 text-xs overflow-hidden"
                          data-testid={`match-log-${index}`}
                        >
                          <CollapsibleTrigger className="w-full p-3 hover:bg-secondary/80 transition-colors">
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex-1 min-w-0 text-left">
                                <div className="flex items-center gap-2">
                                  <Trophy className="h-3 w-3 text-amber-500 flex-shrink-0" />
                                  <span className="font-medium text-foreground truncate">
                                    {winner?.title?.slice(0, 35)}...
                                  </span>
                                </div>
                                <div className="flex items-center gap-2 mt-1 text-muted-foreground">
                                  <span className="text-[10px]">beat</span>
                                  <span className="truncate">
                                    {loser?.title?.slice(0, 35)}...
                                  </span>
                                </div>
                              </div>
                              <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180" />
                            </div>
                          </CollapsibleTrigger>
                          
                          <CollapsibleContent>
                            <div className="px-3 pb-3 pt-1 border-t border-border/50">
                              <div className="flex items-start gap-2">
                                <MessageSquare className="h-3 w-3 text-accent mt-0.5 flex-shrink-0" />
                                <p className="text-muted-foreground leading-relaxed">
                                  {match.reasoning || "No reasoning provided"}
                                </p>
                              </div>
                            </div>
                          </CollapsibleContent>
                        </div>
                      </Collapsible>
                    );
                  })}
                  
                  {(!tournament.matches || tournament.matches.filter(m => m.completed).length === 0) && (
                    <div className="text-center py-8 text-muted-foreground">
                      <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2" />
                      <p className="text-sm">Waiting for comparisons...</p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Completed Actions */}
      {tournament.status === 'completed' && (
        <div className="mt-8 flex justify-center">
          <Button 
            size="lg" 
            onClick={() => navigate(`/results/${id}`)}
            data-testid="view-results-btn"
          >
            <Trophy className="h-5 w-5 mr-2" />
            View Final Rankings
            <ArrowRight className="h-5 w-5 ml-2" />
          </Button>
        </div>
      )}
    </div>
  );
}
