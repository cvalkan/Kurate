import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { 
  History, 
  Loader2, 
  Trophy,
  Clock,
  CheckCircle2,
  XCircle,
  Trash2,
  ArrowRight,
  FileText,
  Calendar,
  RefreshCw,
  FileSearch,
  Zap,
  Bot
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Helper to get short model display name
const getModelDisplayName = (llmModel) => {
  if (!llmModel) return null;
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

export default function HistoryPage() {
  const navigate = useNavigate();
  const [tournaments, setTournaments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(null);

  useEffect(() => {
    fetchTournaments();
  }, []);

  const fetchTournaments = async () => {
    try {
      const response = await axios.get(`${API}/tournaments`);
      setTournaments(response.data.tournaments);
    } catch (error) {
      toast.error("Failed to load tournaments");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (tournamentId) => {
    setDeleting(tournamentId);
    try {
      await axios.delete(`${API}/tournaments/${tournamentId}`);
      setTournaments(prev => prev.filter(t => t.id !== tournamentId));
      toast.success("Tournament deleted");
    } catch (error) {
      toast.error("Failed to delete tournament");
    } finally {
      setDeleting(null);
    }
  };

  const getStatusConfig = (status) => {
    switch (status) {
      case 'pending':
        return { 
          icon: Clock, 
          color: 'bg-yellow-100 text-yellow-800 border-yellow-200',
          label: 'Pending'
        };
      case 'running':
        return { 
          icon: RefreshCw, 
          color: 'bg-blue-100 text-blue-800 border-blue-200',
          label: 'Running'
        };
      case 'completed':
        return { 
          icon: CheckCircle2, 
          color: 'bg-green-100 text-green-800 border-green-200',
          label: 'Completed'
        };
      case 'failed':
        return { 
          icon: XCircle, 
          color: 'bg-red-100 text-red-800 border-red-200',
          label: 'Failed'
        };
      default:
        return { 
          icon: Clock, 
          color: 'bg-gray-100 text-gray-800 border-gray-200',
          label: status
        };
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center space-y-4">
          <Loader2 className="h-12 w-12 animate-spin text-accent mx-auto" />
          <p className="text-muted-foreground">Loading history...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container-main py-8" data-testid="history-page">
      {/* Header */}
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-heading-2 flex items-center gap-3">
            <History className="h-8 w-8 text-accent" />
            Tournament History
          </h1>
          <p className="text-muted-foreground mt-1">
            View and manage your past paper ranking tournaments
          </p>
        </div>
        <Button onClick={() => navigate("/")} data-testid="new-tournament-btn">
          <Trophy className="h-4 w-4 mr-2" />
          New Tournament
        </Button>
      </div>

      {/* Tournament List */}
      {tournaments.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <History className="h-16 w-16 text-muted-foreground/30 mx-auto mb-4" />
            <h3 className="font-heading font-semibold text-lg mb-2">No tournaments yet</h3>
            <p className="text-muted-foreground mb-6">
              Start your first paper ranking tournament to see results here
            </p>
            <Button onClick={() => navigate("/")} data-testid="start-first-btn">
              Start First Tournament
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">All Tournaments</CardTitle>
            <CardDescription>
              {tournaments.length} tournament{tournaments.length !== 1 ? 's' : ''} found
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[600px]">
              <div className="space-y-3">
                {tournaments.map((tournament, index) => {
                  const statusConfig = getStatusConfig(tournament.status);
                  const StatusIcon = statusConfig.icon;
                  
                  return (
                    <div 
                      key={tournament.id}
                      className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 p-4 rounded-lg border border-border hover:border-accent/50 transition-all duration-200 animate-fade-in"
                      style={{ animationDelay: `${index * 0.05}s` }}
                      data-testid={`tournament-row-${index}`}
                    >
                      {/* Badges row on mobile */}
                      <div className="flex flex-wrap items-center gap-2">
                        {/* Status Badge */}
                        <Badge 
                          className={`${statusConfig.color} border flex-shrink-0`}
                          data-testid={`status-badge-${index}`}
                        >
                          <StatusIcon className={`h-3 w-3 mr-1 ${tournament.status === 'running' ? 'animate-spin' : ''}`} />
                          {statusConfig.label}
                        </Badge>
                        
                        {/* Deep Analysis Badge */}
                        {tournament.deep_analysis && (
                          <Badge 
                            variant="outline" 
                            className="border-green-300 text-green-700 bg-green-50 flex-shrink-0"
                            data-testid={`deep-analysis-badge-${index}`}
                          >
                            <FileSearch className="h-3 w-3 mr-1" />
                            Deep
                          </Badge>
                        )}
                        
                        {/* UCB Mode Badge */}
                        {tournament.ranking_mode === 'ucb' && (
                          <Badge 
                            variant="outline" 
                            className="border-purple-300 text-purple-700 bg-purple-50 flex-shrink-0"
                            data-testid={`ucb-badge-${index}`}
                          >
                            <Zap className="h-3 w-3 mr-1" />
                            UCB
                          </Badge>
                        )}
                        
                        {/* Model Badge */}
                        {tournament.llm_model && getModelDisplayName(tournament.llm_model) && (
                          <Badge 
                            variant="outline" 
                            className="border-blue-300 text-blue-700 bg-blue-50 flex-shrink-0"
                            data-testid={`model-badge-${index}`}
                          >
                            <Bot className="h-3 w-3 mr-1" />
                            {getModelDisplayName(tournament.llm_model)}
                          </Badge>
                        )}
                        
                        {/* Progress (for running tournaments) - shown in badge row on mobile */}
                        {tournament.status === 'running' && (
                          <span className="text-sm font-mono font-bold text-accent sm:hidden">
                            {tournament.progress || 0}%
                          </span>
                        )}
                      </div>
                      
                      {/* Main Info */}
                      <div className="flex-1 min-w-0">
                        <h3 className="font-heading font-medium text-base truncate">
                          {tournament.category_name}
                        </h3>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground mt-1">
                          {tournament.category !== 'custom' && (
                            <span className="flex items-center gap-1 font-mono">
                              {tournament.category}
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <FileText className="h-3 w-3" />
                            {tournament.num_papers} papers
                          </span>
                          <span className="flex items-center gap-1">
                            <Calendar className="h-3 w-3" />
                            {formatDate(tournament.created_at)}
                          </span>
                        </div>
                      </div>
                      
                      {/* Progress (for running tournaments) - desktop only */}
                      {tournament.status === 'running' && (
                        <div className="hidden sm:block flex-shrink-0 text-right">
                          <span className="text-lg font-mono font-bold text-accent">
                            {tournament.progress || 0}%
                          </span>
                        </div>
                      )}
                      
                      {/* Actions */}
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {tournament.status === 'completed' && (
                          <Button 
                            size="sm"
                            onClick={() => navigate(`/results/${tournament.id}`)}
                            data-testid={`view-results-${index}`}
                          >
                            Results
                            <ArrowRight className="h-3 w-3 ml-1" />
                          </Button>
                        )}
                        
                        {tournament.status === 'running' && (
                          <Button 
                            size="sm"
                            variant="outline"
                            onClick={() => navigate(`/tournament/${tournament.id}`)}
                            data-testid={`view-progress-${index}`}
                          >
                            View Progress
                          </Button>
                        )}
                        
                        {tournament.status === 'pending' && (
                          <Button 
                            size="sm"
                            variant="outline"
                            onClick={() => navigate(`/tournament/${tournament.id}`)}
                            data-testid={`view-pending-${index}`}
                          >
                            View
                          </Button>
                        )}

                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button 
                              size="icon" 
                              variant="ghost"
                              className="text-muted-foreground hover:text-destructive"
                              disabled={deleting === tournament.id}
                              data-testid={`delete-btn-${index}`}
                            >
                              {deleting === tournament.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Trash2 className="h-4 w-4" />
                              )}
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Delete Tournament?</AlertDialogTitle>
                              <AlertDialogDescription>
                                This will permanently delete the tournament &ldquo;{tournament.category_name}&rdquo; and all its results.
                                This action cannot be undone.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction 
                                onClick={() => handleDelete(tournament.id)}
                                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                              >
                                Delete
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
